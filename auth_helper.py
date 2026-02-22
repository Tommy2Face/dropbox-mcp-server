"""
Dropbox OAuth2 Helper
Run this script to get a refresh token for the MCP server.

Usage:
    python auth_helper.py

Prerequisites:
    1. Create a Dropbox app at https://www.dropbox.com/developers/apps
    2. Set permissions: files.metadata.read/write, files.content.read/write, sharing.read/write
    3. Note your App Key and App Secret
"""

import webbrowser
from dropbox import DropboxOAuth2FlowNoRedirect


def main():
    print("=" * 60)
    print("  Dropbox OAuth2 Setup Helper")
    print("=" * 60)
    print()

    app_key = input("Enter your Dropbox App Key: ").strip()
    if not app_key:
        print("Error: App key is required.")
        return

    app_secret = input("Enter your Dropbox App Secret: ").strip()
    if not app_secret:
        print("Error: App secret is required.")
        return

    auth_flow = DropboxOAuth2FlowNoRedirect(
        app_key,
        consumer_secret=app_secret,
        token_access_type="offline",
    )

    authorize_url = auth_flow.start()

    print()
    print("1. Opening your browser to authorize the app...")
    print(f"   URL: {authorize_url}")
    print()

    webbrowser.open(authorize_url)

    auth_code = input("2. Paste the authorization code here: ").strip()
    if not auth_code:
        print("Error: Authorization code is required.")
        return

    try:
        oauth_result = auth_flow.finish(auth_code)
    except Exception as e:
        print(f"Error: Could not complete authorization: {e}")
        return

    print()
    print("=" * 60)
    print("  Success! Here are your credentials:")
    print("=" * 60)
    print()
    print(f"  DROPBOX_APP_KEY={app_key}")
    print(f"  DROPBOX_APP_SECRET={app_secret}")
    print(f"  DROPBOX_REFRESH_TOKEN={oauth_result.refresh_token}")
    print()
    print("Add these to your .env file, or use them in your")
    print("Claude Desktop / Cursor MCP configuration.")
    print()


if __name__ == "__main__":
    main()
