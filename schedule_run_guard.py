"""Allow one successful or active production run per Toronto evening."""
import json
import os
from datetime import datetime, time
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def main():
    should_run = True
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        try:
            zone = ZoneInfo("America/Toronto")
            now = datetime.now(zone)
            cutoff = datetime.combine(
                now.date(),
                time(int(os.environ["CUTOFF_HOUR"]), int(os.environ["CUTOFF_MINUTE"])),
                tzinfo=zone,
            )
            repository = os.environ["GITHUB_REPOSITORY"]
            workflow = os.environ["WORKFLOW_FILE"]
            url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/runs?per_page=100"
            request = Request(url, headers={
                "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            })
            with urlopen(request, timeout=20) as response:
                runs = json.load(response)["workflow_runs"]
            for previous in runs:
                if str(previous["id"]) == os.environ["GITHUB_RUN_ID"]:
                    continue
                created = datetime.fromisoformat(previous["created_at"].replace("Z", "+00:00")).astimezone(zone)
                if created < cutoff or created.date() != now.date():
                    continue
                if previous["status"] != "completed" or previous.get("conclusion") == "success":
                    print(f"Skip duplicate: run {previous['id']} is {previous['status']}/{previous.get('conclusion')}")
                    should_run = False
                    break
        except Exception as exc:
            print(f"Schedule guard could not check recent runs; proceeding: {type(exc).__name__}: {exc}")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"run={str(should_run).lower()}\n")
    print(f"Production run allowed: {should_run}")


if __name__ == "__main__":
    main()
