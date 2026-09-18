import os

import pytest
import mongomock
import mongoengine
from fastapi.testclient import TestClient

from main import app
from app.core.security import create_access_token
from app.services.user_service import UserService

client = TestClient(app)
ADMIN_EMAIL = os.environ["PLATFORM_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ["PLATFORM_ADMIN_PASSWORD"]

mongoengine.disconnect_all()
mongoengine.connect(
    "soc_mind_platform",
    host="mongodb://root:example@mongodb:27017/",
    mongo_client_class=mongomock.MongoClient,
    alias="default",
    uuidRepresentation="standard",
)

import app.db.mongodb
import app.services.tenant_service


class MockDatabaseManager:
    @staticmethod
    def initialize():
        pass

    @staticmethod
    def get_tenant_db_alias(db_name: str) -> str:
        alias = f"tenant_{db_name}"
        if alias not in mongoengine.connection._connections:
            mongoengine.connect(
                db_name,
                host="mongodb://root:example@mongodb:27017/",
                mongo_client_class=mongomock.MongoClient,
                alias=alias,
                uuidRepresentation="standard",
            )
        return alias

    @staticmethod
    def get_tenant_database(db_name: str):
        alias = MockDatabaseManager.get_tenant_db_alias(db_name)
        return mongoengine.connection.get_db(alias)


def get_admin_token() -> str:
    return create_access_token(
        user_id="test-admin-id",
        email=ADMIN_EMAIL,
        role="PLATFORM_ADMIN",
        tenant_id=None,
    )


def get_auth_headers() -> dict:
    return {"Authorization": f"Bearer {get_admin_token()}"}


@pytest.fixture(autouse=True)
def mock_mongo(monkeypatch):
    monkeypatch.setattr(app.db.mongodb, "DatabaseManager", MockDatabaseManager)
    monkeypatch.setattr(app.services.tenant_service, "DatabaseManager", MockDatabaseManager)
    yield


@pytest.fixture(autouse=True)
def clean_db(mock_mongo):
    from app.models.tenant import Tenant
    from app.models.user import User

    Tenant.drop_collection()
    User.drop_collection()
    yield


@pytest.fixture
def sample_tenant():
    """Create a tenant to associate users with."""
    headers = get_auth_headers()
    r = client.post(
        "/api/v1/admin/tenants",
        json={"name": "user-test-org", "display_name": "User Test Org"},
        headers=headers,
    )
    return r.json()


# --- Auth / Login Tests ---


def test_seed_and_login():
    UserService.seed_platform_admin()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password():
    UserService.seed_platform_admin()

    response = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": "wrong"},
    )
    assert response.status_code == 401


def test_login_nonexistent_user():
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 401


def test_get_me():
    UserService.seed_platform_admin()

    login_r = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    token = login_r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_r = client.get("/api/v1/auth/me", headers=headers)
    assert me_r.status_code == 200
    data = me_r.json()
    assert data["email"] == ADMIN_EMAIL
    assert data["role"] == "PLATFORM_ADMIN"
    assert data["tenant_id"] is None
    assert "hashed_password" not in data


# --- User CRUD Tests ---


def test_create_tenant_admin_user(sample_tenant):
    headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "alice@example.com",
            "password": "securepass123",
            "role": "TENANT_ADMIN",
            "tenant_id": tenant_id,
        },
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert data["role"] == "TENANT_ADMIN"
    assert data["tenant_id"] == tenant_id
    assert "hashed_password" not in data


def test_create_tenant_operator_user(sample_tenant):
    headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "bob@example.com",
            "password": "securepass123",
            "role": "TENANT_OPERATOR",
            "tenant_id": tenant_id,
        },
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["role"] == "TENANT_OPERATOR"


def test_create_tenant_admin_without_tenant_id_fails():
    headers = get_auth_headers()

    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "alice@example.com",
            "password": "securepass123",
            "role": "TENANT_ADMIN",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "tenant_id" in response.json()["detail"].lower()


def test_create_platform_admin_with_tenant_id_fails():
    headers = get_auth_headers()

    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "superadmin@example.com",
            "password": "securepass123",
            "role": "PLATFORM_ADMIN",
            "tenant_id": "some-tenant",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert "platform_admin" in response.json()["detail"].lower()


def test_create_user_with_nonexistent_tenant_fails():
    headers = get_auth_headers()

    response = client.post(
        "/api/v1/admin/users",
        json={
            "email": "alice@example.com",
            "password": "securepass123",
            "role": "TENANT_ADMIN",
            "tenant_id": "nonexistent-tenant-id",
        },
        headers=headers,
    )
    assert response.status_code == 404


def test_create_duplicate_user_fails(sample_tenant):
    headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]
    user_data = {
        "email": "dupe@example.com",
        "password": "securepass123",
        "role": "TENANT_ADMIN",
        "tenant_id": tenant_id,
    }

    client.post("/api/v1/admin/users", json=user_data, headers=headers)
    response = client.post("/api/v1/admin/users", json=user_data, headers=headers)
    assert response.status_code == 409


def test_list_users(sample_tenant):
    headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    client.post(
        "/api/v1/admin/users",
        json={
            "email": "u1@example.com",
            "password": "securepass123",
            "role": "TENANT_OPERATOR",
            "tenant_id": tenant_id,
        },
        headers=headers,
    )
    client.post(
        "/api/v1/admin/users",
        json={
            "email": "u2@example.com",
            "password": "securepass123",
            "role": "TENANT_OPERATOR",
            "tenant_id": tenant_id,
        },
        headers=headers,
    )

    response = client.get("/api/v1/admin/users", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_users_filter_by_tenant(sample_tenant):
    headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    client.post(
        "/api/v1/admin/users",
        json={
            "email": "u1@example.com",
            "password": "securepass123",
            "role": "TENANT_OPERATOR",
            "tenant_id": tenant_id,
        },
        headers=headers,
    )

    response = client.get(
        f"/api/v1/admin/users?tenant_id={tenant_id}", headers=headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    response = client.get(
        "/api/v1/admin/users?tenant_id=nonexistent", headers=headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 0


def test_get_user_by_id(sample_tenant):
    headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    create_r = client.post(
        "/api/v1/admin/users",
        json={
            "email": "getme@example.com",
            "password": "securepass123",
            "role": "TENANT_ADMIN",
            "tenant_id": tenant_id,
        },
        headers=headers,
    )
    user_id = create_r.json()["user_id"]

    response = client.get(f"/api/v1/admin/users/{user_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == "getme@example.com"


def test_get_nonexistent_user():
    headers = get_auth_headers()
    response = client.get("/api/v1/admin/users/nonexistent", headers=headers)
    assert response.status_code == 404


# --- Authorization Tests ---


def test_tenant_admin_cannot_manage_users(sample_tenant):
    tenant_id = sample_tenant["tenant_id"]
    tenant_admin_token = create_access_token(
        user_id="ta-1",
        email="ta@example.com",
        role="TENANT_ADMIN",
        tenant_id=tenant_id,
    )
    headers = {"Authorization": f"Bearer {tenant_admin_token}"}

    response = client.get("/api/v1/admin/users", headers=headers)
    assert response.status_code == 403


def test_operator_cannot_manage_users(sample_tenant):
    tenant_id = sample_tenant["tenant_id"]
    operator_token = create_access_token(
        user_id="op-1",
        email="operator@example.com",
        role="TENANT_OPERATOR",
        tenant_id=tenant_id,
    )
    headers = {"Authorization": f"Bearer {operator_token}"}

    response = client.get("/api/v1/admin/users", headers=headers)
    assert response.status_code == 403

    response = client.get(
        f"/api/v1/tenants/{tenant_id}/users", headers=headers
    )
    assert response.status_code == 403


# --- Tenant-Scoped User Endpoints ---


def test_tenant_admin_list_own_users(sample_tenant):
    admin_headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    client.post(
        "/api/v1/admin/users",
        json={
            "email": "ta@example.com",
            "password": "securepass123",
            "role": "TENANT_ADMIN",
            "tenant_id": tenant_id,
        },
        headers=admin_headers,
    )
    client.post(
        "/api/v1/admin/users",
        json={
            "email": "op@example.com",
            "password": "securepass123",
            "role": "TENANT_OPERATOR",
            "tenant_id": tenant_id,
        },
        headers=admin_headers,
    )

    ta_token = create_access_token(
        user_id="ta-1", email="ta@example.com", role="TENANT_ADMIN", tenant_id=tenant_id
    )
    ta_headers = {"Authorization": f"Bearer {ta_token}"}

    response = client.get(f"/api/v1/tenants/{tenant_id}/users", headers=ta_headers)
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_tenant_admin_create_operator(sample_tenant):
    admin_headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    client.post(
        "/api/v1/admin/users",
        json={
            "email": "ta@example.com",
            "password": "securepass123",
            "role": "TENANT_ADMIN",
            "tenant_id": tenant_id,
        },
        headers=admin_headers,
    )

    ta_token = create_access_token(
        user_id="ta-1", email="ta@example.com", role="TENANT_ADMIN", tenant_id=tenant_id
    )
    ta_headers = {"Authorization": f"Bearer {ta_token}"}

    response = client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={"email": "newop@example.com", "password": "securepass123", "role": "TENANT_OPERATOR"},
        headers=ta_headers,
    )
    assert response.status_code == 201
    assert response.json()["role"] == "TENANT_OPERATOR"
    assert response.json()["tenant_id"] == tenant_id


def test_tenant_admin_cannot_create_tenant_admin(sample_tenant):
    tenant_id = sample_tenant["tenant_id"]
    ta_token = create_access_token(
        user_id="ta-1", email="ta@example.com", role="TENANT_ADMIN", tenant_id=tenant_id
    )
    ta_headers = {"Authorization": f"Bearer {ta_token}"}

    response = client.post(
        f"/api/v1/tenants/{tenant_id}/users",
        json={"email": "sneaky@example.com", "password": "securepass123", "role": "TENANT_ADMIN"},
        headers=ta_headers,
    )
    assert response.status_code == 403


def test_tenant_admin_cannot_access_other_tenant(sample_tenant):
    tenant_id = sample_tenant["tenant_id"]
    ta_token = create_access_token(
        user_id="ta-1", email="ta@example.com", role="TENANT_ADMIN", tenant_id=tenant_id
    )
    ta_headers = {"Authorization": f"Bearer {ta_token}"}

    response = client.get("/api/v1/tenants/other-tenant-id/users", headers=ta_headers)
    assert response.status_code == 403


def test_tenant_user_login_and_jwt_claims(sample_tenant):
    admin_headers = get_auth_headers()
    tenant_id = sample_tenant["tenant_id"]

    client.post(
        "/api/v1/admin/users",
        json={
            "email": "alice@example.com",
            "password": "securepass123",
            "role": "TENANT_ADMIN",
            "tenant_id": tenant_id,
        },
        headers=admin_headers,
    )

    login_r = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "securepass123"},
    )
    assert login_r.status_code == 200
    token = login_r.json()["access_token"]

    me_r = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_r.status_code == 200
    data = me_r.json()
    assert data["email"] == "alice@example.com"
    assert data["role"] == "TENANT_ADMIN"
    assert data["tenant_id"] == tenant_id
