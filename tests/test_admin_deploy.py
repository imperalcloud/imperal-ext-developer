"""A platform admin deploys another developer's app -- safely (the owner 2026-11-26).

The author alone could press deploy: the gateway answers 404 to anyone who is not the app's owner. A fix
the author merged into their own main branch then waited for the author's click while users met the bug.

What must hold, whoever presses:
- the gateway decides who is an admin (the role in ctx is only the reason to ask the admin door);
- the code comes from the app's registered git_url -- the caller names no address, branch or commit;
- the app stays its author's (registry owner = the author, never the admin);
- the deploy is recorded by the admin door, and a lost record is told, not passed in silence.
"""
import asyncio
import inspect
from types import SimpleNamespace

import pytest

import deploy_sync
import handlers_deploy


def _ctx(role, uid="imp_u_caller"):
    return SimpleNamespace(user=SimpleNamespace(imperal_id=uid, role=role))


def _gateway(monkeypatch, own=None, any_owner=None):
    asked = []

    async def gw_get(path):
        asked.append(path)
        if path.startswith("/v1/developer/apps/"):
            if own is None:
                raise ValueError("404 App 'x' not found")
            return own
        if path.startswith("/v1/admin/apps/"):
            if any_owner is None:
                raise ValueError("403 Admin access required")
            return any_owner
        raise AssertionError(path)

    monkeypatch.setattr(handlers_deploy, "_gw_get", gw_get)
    return asked


def test_the_author_deploys_their_own_app_by_the_developer_door(monkeypatch):
    asked = _gateway(monkeypatch, own={"app_id": "x", "developer_id": "imp_u_caller"})
    app, door = asyncio.run(handlers_deploy.app_for_deploy(_ctx("developer"), "x"))
    assert door == "developer" and app["app_id"] == "x"
    assert asked == ["/v1/developer/apps/x?user_id=imp_u_caller"]          # the admin door is not even asked


def test_a_developer_who_is_not_the_owner_never_reaches_the_admin_door(monkeypatch):
    asked = _gateway(monkeypatch, own=None, any_owner={"app_id": "x", "developer_id": "imp_u_author"})
    with pytest.raises(ValueError):
        asyncio.run(handlers_deploy.app_for_deploy(_ctx("developer"), "x"))
    assert all(p.startswith("/v1/developer/") for p in asked)


def test_an_admin_reads_another_developers_app_by_the_admin_door_naming_themself(monkeypatch):
    asked = _gateway(monkeypatch, own=None, any_owner={"app_id": "x", "developer_id": "imp_u_author"})
    app, door = asyncio.run(handlers_deploy.app_for_deploy(_ctx("admin", "imp_u_admin"), "x"))
    assert door == "admin" and app["developer_id"] == "imp_u_author"
    assert asked[-1] == "/v1/admin/apps/x/deploy-source?user_id=imp_u_admin"  # -> X-Acting-User: the gateway proves it


def test_the_gateway_has_the_last_word_on_who_is_an_admin(monkeypatch):
    # ctx says admin, the gateway says no: no app, no deploy
    _gateway(monkeypatch, own=None, any_owner=None)
    with pytest.raises(ValueError, match="403"):
        asyncio.run(handlers_deploy.app_for_deploy(_ctx("admin"), "x"))


def test_the_caller_names_no_address_branch_or_commit():
    assert set(handlers_deploy.DeployParams.model_fields) == {"app_id"}
    src = inspect.getsource(handlers_deploy.deploy_app)
    assert 'git_url = app_info.get("git_url", "")' in src                 # the registered address, from the gateway


def test_the_app_stays_its_authors_and_every_record_goes_by_the_door_it_was_read_by():
    src = inspect.getsource(handlers_deploy.deploy_app)
    assert 'owner = (app_info.get("developer_id") or uid) if door == "admin" else uid' in src
    assert "_sync_tools_to_registry(app_id, app_dir, owner_id=owner)" in src
    assert "owner_id=uid" not in src
    calls = src.count("await _record_deploy(")
    assert calls == 3 and src.count(", door)") + src.count(", door,\n") == calls


def test_a_deploy_record_goes_to_the_door_and_its_loss_is_told(monkeypatch):
    posted = []

    async def ok(path, data):
        posted.append((path, data))
        return {}

    async def down(path, data):
        raise ValueError("API error 503")

    monkeypatch.setattr(deploy_sync, "_gw_post", ok)
    assert asyncio.run(deploy_sync._record_deploy("imp_u_admin", "x", "abc", "success", "", "admin")) is True
    assert asyncio.run(deploy_sync._record_deploy("imp_u_a", "x", "abc", "success", "")) is True
    assert [p for p, _ in posted] == ["/v1/admin/apps/x/deploys", "/v1/developer/apps/x/deploys"]
    assert posted[0][1]["user_id"] == "imp_u_admin"                        # who deployed = the admin
    monkeypatch.setattr(deploy_sync, "_gw_post", down)
    assert asyncio.run(deploy_sync._record_deploy("imp_u_admin", "x", "abc", "success", "", "admin")) is False
    assert "NOT written" in inspect.getsource(handlers_deploy.deploy_app)


@pytest.mark.parametrize("app_id", [
    "x?user_id=imp_u_admin&", "x%3Fuser_id=imp_u_admin", "../developer", "x/../../admin/apps/y", "x#", "x y", "",
    "x&user_id=imp_u_admin", "x?a=1", "x&a=1",
])
def test_an_app_id_can_never_name_who_is_acting_or_leave_its_path(app_id):
    # the acting user is read from the path's query: what the caller typed must not be able to write one
    import app
    for path in (f"/v1/developer/apps/{app_id}?user_id=imp_u_caller",
                 f"/v1/admin/apps/{app_id}/deploy-source?user_id=imp_u_caller",
                 f"/v1/developer/apps/{app_id}/deploys"):
        with pytest.raises(ValueError, match="refused"):
            app._acting_headers(path, {"user_id": "imp_u_caller"})


def test_every_gateway_helper_passes_the_path_check_and_the_paths_the_extension_builds_pass_it():
    import app
    for helper in (app._gw_get, app._gw_post, app._gw_put, app._gw_delete):
        assert "_acting_headers(path" in inspect.getsource(helper)
    assert "_refuse_unclean_path(path)" in inspect.getsource(app._acting_headers)
    assert app._acting_headers("/v1/admin/apps/wordpress-hub/deploy-source?user_id=imp_u_tE-J9c_NxX") == {
        "X-Acting-User": "imp_u_tE-J9c_NxX"}
    for ok in ("/v1/developer/apps?user_id=imp_u_a", "/v1/marketplace/categories/catalog",
               "/v1/developer/earnings/my_app-2?user_id=imp_u_a", "/v1/developer/payouts/request"):
        app._acting_headers(ok, {"user_id": "imp_u_a"})


def test_the_panel_config_path_of_a_deploy_passes_and_names_nobody():
    # live 2026-11-26 22:33 UTC: the first shape of this check knew only ``?user_id=`` and refused the path
    # every deploy syncs its panels by -- "Panel config sync failed for wordpress-hub: refused"
    import app
    path = "/v1/internal/config/app/wordpress-hub?tenant_id=default&app_id=wordpress-hub"
    assert app._acting_headers(path, {"config": {}}) == {}
    assert app._acting_headers("/v1/developer/apps/x/_sync_manifest", {"manifest_json": {}}) == {}


@pytest.mark.parametrize("path", [
    "/v1/internal/config/app/x?tenant_id=default&app_id=x&user_id=imp_u_admin",     # an acting user slipped in last
    "/v1/internal/config/app/x?tenant_id=default&user_id=imp_u_admin&app_id=x",
    "/v1/developer/apps/x?user_id=imp_u_a&user_id=imp_u_admin",
    "/v1/internal/config/app/x?tenant_id=default&app_id=x%26user_id%3Dimp_u_admin",
    "/v1/internal/config/app/x?tenant_id=default&app_id=",
])
def test_an_acting_user_can_stand_only_first_in_a_query(path):
    import app
    with pytest.raises(ValueError, match="refused"):
        app._acting_headers(path, {})
