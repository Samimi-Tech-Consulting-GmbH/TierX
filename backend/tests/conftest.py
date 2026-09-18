import os


# Unit tests do not read the repository's local .env file. Supply explicit,
# non-production values before test modules import the application.
os.environ.setdefault("PYTHON_ENV", "test")
os.environ.setdefault("MONGO_URL", "mongodb://unit-test.invalid/")
os.environ.setdefault("JWT_SECRET_KEY", "unit-test-jwt-key-not-for-deployment")
os.environ.setdefault("PLATFORM_ADMIN_EMAIL", "test-admin@example.com")
os.environ.setdefault("PLATFORM_ADMIN_PASSWORD", "unit-test-admin-password")
