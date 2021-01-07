import os
from pathlib import Path
basedir = Path(__file__).parent
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())


class Config(object):
    DEBUG = False
    TESTING = False
    CSRF_ENABLED = True
    SECRET_KEY = os.environ.get('SECRET_KEY', None)
    # 16MB upper limit
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

    AUTHORITY = f"https://login.microsoftonline.com/{os.environ.get('TENANT_ID')}"

    # Application (client) ID of app registration
    CLIENT_ID = os.environ.get('CLIENT_ID')

    CLIENT_SECRET = os.environ.get('CLIENT_SECRET')

    REDIRECT_PATH = "/oauth_callback"  # Used for forming an absolute URL to your redirect URI.
    # The absolute URL must match the redirect URI you set
    # in the app's registration in the Azure portal.

    # This is the API resource endpoint
    ENDPOINT = ''  # Application ID URI of app registration in Azure portal

    # These are the scopes you've exposed in the web API app registration in the Azure portal
    SCOPE = []  # Example with two exposed scopes: ["demo.read", "demo.write"]

    SESSION_TYPE = "filesystem"  # Specifies the token cache should be stored in server-side session


class ProductionConfig(Config):
    DEBUG = False


class StagingConfig(Config):
    DEVELOPMENT = True
    DEBUG = True


class DevelopmentConfig(Config):
    DEVELOPMENT = True
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
