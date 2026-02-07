import os
import time
import requests
import hashlib
from github import Github


def get_github_latest_release():
    g = Github()
    repo = g.get_repo("nezhahq/nezha")
    release = repo.get_latest_release()
    if release:
        print(f"Latest release tag is: {release.tag_name}")
        print(f"Latest release info is: {release.body}")
        files = []
        for asset in release.get_assets():
            url = asset.browser_download_url
            name = asset.name

            response = requests.get(url)
            if response.status_code == 200:
                with open(name, "wb") as f:
                    f.write(response.content)
                print(f"Downloaded {name}")
            else:
                print(f"Failed to download {name}")
            file_abs_path = get_abs_path(asset.name)
            files.append(file_abs_path)
        sync_to_gitee(release.tag_name, release.body, files)
    else:
        print("No releases found.")


def delete_gitee_releases(latest_id, client, uri, token):
    get_data = {"access_token": token}

    release_info = []
    release_response = client.get(uri, json=get_data)
    if release_response.status_code == 200:
        release_info = release_response.json()
    else:
        print(f"Request failed with status code {release_response.status_code}")

    release_ids = []
    for block in release_info:
        if "id" in block:
            release_ids.append(block["id"])

    print(f"Current release ids: {release_ids}")
    release_ids.remove(latest_id)

    for id in release_ids:
        release_uri = f"{uri}/{id}"
        delete_data = {"access_token": token}
        delete_response = client.delete(release_uri, json=delete_data)
        if delete_response.status_code == 204:
            print(f"Successfully deleted release #{id}.")
        else:
            raise ValueError(
                f"Request failed with status code {delete_response.status_code}"
            )


def sync_to_gitee(tag: str, body: str, files: list):
    release_id = ""
    owner = "naibahq"
    repo = "nezha"
    release_api_uri = f"https://gitee.com/api/v5/repos/{owner}/{repo}/releases"
    api_client = requests.Session()
    api_client.headers.update(
        {"Accept": "application/json", "Content-Type": "application/json"}
    )

    max_retries = 5
    access_token = os.environ["GITEE_TOKEN"]
    release_data = {
        "access_token": access_token,
        "tag_name": tag,
        "name": tag,
        "body": body,
        "prerelease": False,
        "target_commitish": "master",
    }
    # Check if release already exists for this tag
    release_id = None
    try:
        list_response = api_client.get(
            release_api_uri, params={"access_token": access_token}, timeout=30
        )
        if list_response.status_code == 200:
            for rel in list_response.json():
                if rel.get("tag_name") == tag:
                    release_id = rel.get("id")
                    print(f"Found existing Gitee release for {tag}, id: {release_id}")
                    break
    except requests.exceptions.RequestException as err:
        print(f"Failed to check existing releases: {err}")

    # Create new release if not found
    if release_id is None:
        release_api_response = None
        for attempt in range(max_retries):
            try:
                release_api_response = api_client.post(
                    release_api_uri, json=release_data, timeout=30
                )
                release_api_response.raise_for_status()
                break
            except requests.exceptions.Timeout as errt:
                print(f"Request timed out: {errt} Retrying in 60 seconds...")
                time.sleep(60)
            except requests.exceptions.RequestException as err:
                print(f"Request failed: {err}")
                break

        if release_api_response is None or release_api_response.status_code != 201:
            print("Failed to create Gitee release")
            api_client.close()
            return

        release_info = release_api_response.json()
        release_id = release_info.get("id")

    print(f"Gitee release id: {release_id}")
    asset_api_uri = f"{release_api_uri}/{release_id}/attach_files"

    for file_path in files:
        success = False
        retries = 0

        while not success and retries < max_retries:
            try:
                with open(file_path, "rb") as f:
                    upload_files = {"file": f}

                    asset_api_response = requests.post(
                        asset_api_uri,
                        params={"access_token": access_token},
                        files=upload_files,
                        timeout=300,
                    )

                if asset_api_response.status_code == 201:
                    asset_info = asset_api_response.json()
                    asset_name = asset_info.get("name")
                    print(f"Successfully uploaded {asset_name}!")
                    success = True
                else:
                    retries += 1
                    print(
                        f"Request failed with status code {asset_api_response.status_code}, retry {retries}/{max_retries}"
                    )
                    if retries < max_retries:
                        time.sleep(30)
            except requests.exceptions.RequestException as err:
                retries += 1
                print(f"Upload error: {err}, retry {retries}/{max_retries}")
                if retries < max_retries:
                    time.sleep(30)

        if not success:
            print(f"Failed to upload {file_path} after {max_retries} retries")

    # 仅保留最新 Release 以防超出 Gitee 仓库配额
    try:
        delete_gitee_releases(release_id, api_client, release_api_uri, access_token)
    except ValueError as e:
        print(e)

    api_client.close()
    print("Sync is completed!")


def get_abs_path(path: str):
    wd = os.getcwd()
    return os.path.join(wd, path)


get_github_latest_release()
