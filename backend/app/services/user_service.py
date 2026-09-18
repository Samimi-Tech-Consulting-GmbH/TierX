import logging
import os
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

import bcrypt

from app.models.user import User
from app.schemas.user import UserCreate, UserDocument, UserRole
from app.core.errors import DuplicateResourceError, ResourceNotFoundError

logger = logging.getLogger(__name__)


class UserService:
    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(
            plain.encode("utf-8"), hashed.encode("utf-8")
        )

    @classmethod
    def _to_document(cls, user: User) -> UserDocument:
        doc_dict = user.to_mongo().to_dict()
        doc_dict["_id"] = str(doc_dict["_id"])
        return UserDocument(**doc_dict)

    @classmethod
    def create_user(cls, user_in: UserCreate, created_by: str) -> UserDocument:
        if User.objects(email=user_in.email).first():
            raise DuplicateResourceError(
                f"User with email {user_in.email} already exists"
            )

        if user_in.role != UserRole.PLATFORM_ADMIN and not user_in.tenant_id:
            raise ValueError("tenant_id is required for non-platform-admin roles")

        if user_in.role == UserRole.PLATFORM_ADMIN and user_in.tenant_id:
            raise ValueError("PLATFORM_ADMIN users cannot be assigned to a tenant")

        if user_in.tenant_id:
            from app.models.tenant import Tenant

            if not Tenant.objects(tenant_id=user_in.tenant_id).first():
                raise ResourceNotFoundError(
                    f"Tenant {user_in.tenant_id} not found"
                )

        new_user = User(
            user_id=str(uuid4()),
            email=user_in.email,
            hashed_password=cls.hash_password(user_in.password),
            role=user_in.role.value,
            tenant_id=user_in.tenant_id,
            created_by=created_by,
        )
        new_user.save()

        return cls._to_document(new_user)

    @classmethod
    def authenticate(cls, email: str, password: str) -> Optional[User]:
        user = User.objects(email=email, is_active=True).first()
        if not user or not cls.verify_password(password, user.hashed_password):
            return None
        return user

    @classmethod
    def get_user_by_id(cls, user_id: str) -> UserDocument:
        user = User.objects(user_id=user_id).first()
        if not user:
            raise ResourceNotFoundError(f"User {user_id} not found")
        return cls._to_document(user)

    @classmethod
    def get_users(
        cls,
        skip: int = 0,
        limit: int = 100,
        tenant_id: Optional[str] = None,
        role: Optional[UserRole] = None,
    ) -> List[UserDocument]:
        query = User.objects
        if tenant_id:
            query = query(tenant_id=tenant_id)
        if role:
            query = query(role=role.value)
        users = query.skip(skip).limit(limit)
        return [cls._to_document(u) for u in users]

    @classmethod
    def seed_platform_admin(
        cls,
        email: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        email = email or os.environ["PLATFORM_ADMIN_EMAIL"]
        password = password or os.environ["PLATFORM_ADMIN_PASSWORD"]
        if User.objects(email=email).first():
            return
        admin = User(
            user_id=str(uuid4()),
            email=email,
            hashed_password=cls.hash_password(password),
            role=UserRole.PLATFORM_ADMIN.value,
            tenant_id=None,
            created_by="system",
        )
        admin.save()
        logger.info("Seeded platform admin user: %s", email)
