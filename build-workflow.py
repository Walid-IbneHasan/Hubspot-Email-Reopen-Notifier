"""Create or update the "Repeat Open Alerts" HubSpot workflow from repeat-open-alert.js.

Usage:
  python build-workflow.py            # create a new workflow (created switched OFF)
  python build-workflow.py <flowId>   # push the code + notification step into an existing workflow

Reads HUBSPOT_TOKEN from .env in this folder. Settings below control the trigger filter and the
notification channel. Saving this file alone changes nothing in HubSpot; running it does.
"""
import json, os, sys, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.hubapi.com"
PORTAL = "43646194"

# ---- Settings -----------------------------------------------------------------------------
WORKFLOW_NAME = "Repeat Open Alerts - KSHSAA High School AD List (351) - Slack on 2+ opens"

# Only contacts in this HubSpot list can enroll. "" = every contact.
# 1135 = "KSHSAA High School AD List - 8.20.26" (static, 351 contacts)
ENROLL_LIST_ID = "1135"

# "slack" or "email"
NOTIFY_VIA = "slack"

# Slack: channel IDs and/or Slack user IDs (direct messages). Pick them in the HubSpot UI on the
# Slack step if unsure; the IDs show up here after a GET. At least one is required.
SLACK_CHANNEL_IDS = ["C0BLUKF29S7"]   # placeholder: channel used by "KSHSAA Inquiry Form Slack Notification"
SLACK_USER_IDS = []

# Email: HubSpot user IDs who get the internal email notification.
EMAIL_USER_IDS = ["82343933", "66809179"]   # Joe Davis, Riley Simpson
# ----------------------------------------------------------------------------------------------

RECORD_LINK = "https://app.hubspot.com/contacts/" + PORTAL + "/record/0-1/{{ enrolled_object.hs_object_id }}"


def load_env():
    env = {}
    with open(os.path.join(HERE, ".env"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def call(token, method, path, body=None):
    req = urllib.request.Request(API + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw}


def custom_code_action(source, next_id):
    return {
        "actionId": "1",
        "type": "CUSTOM_CODE",
        "runtime": "NODE20X",
        "sourceCode": source,
        "secretNames": ["HUBSPOT_TOKEN"],
        "inputFields": [],
        "outputFields": [
            {"name": "notify", "type": "STRING"},
            {"name": "email_name", "type": "STRING"},
            {"name": "open_count", "type": "STRING"},
            {"name": "reason", "type": "STRING"},
        ],
        "connection": {"edgeType": "STANDARD", "nextActionId": next_id},
    }


def notification_action(action_id, next_id):
    """The alert step: Slack (HubSpot's Slack integration action) or internal email."""
    if NOTIFY_VIA == "slack":
        message = (
            ":repeat: *Repeat open alert*\n"
            "*{{ enrolled_object.firstname }} {{ enrolled_object.lastname }}* ({{ enrolled_object.email }}) "
            "opened the same email *{{ enrolled_object.repeat_open_alert_count }} times*.\n"
            "Email: {{ enrolled_object.repeat_open_alert_email }}\n"
            "Alerts for this contact so far: {{ enrolled_object.repeat_open_alert_total }}\n"
            "Contact record: " + RECORD_LINK
        )
        return {
            "actionId": action_id,
            "type": "SINGLE_CONNECTION",
            "actionTypeId": "1-179507819",
            "actionTypeVersion": 2,
            "fields": {
                "slackChannelIds": SLACK_CHANNEL_IDS,
                "slackUserIds": SLACK_USER_IDS,
                "notifyOwner": [],
                "message": message,
            },
            "connection": {"edgeType": "STANDARD", "nextActionId": next_id},
        }
    subject = ("Repeat open: {{ enrolled_object.firstname }} {{ enrolled_object.lastname }} opened "
               "\"{{ enrolled_object.repeat_open_alert_email }}\" {{ enrolled_object.repeat_open_alert_count }} times")
    body = (
        "<p>A contact opened the same marketing email more than once.</p>"
        "<p><strong>Contact:</strong> {{ enrolled_object.firstname }} {{ enrolled_object.lastname }} "
        "({{ enrolled_object.email }})<br>"
        "<strong>Email:</strong> {{ enrolled_object.repeat_open_alert_email }}<br>"
        "<strong>Real opens so far:</strong> {{ enrolled_object.repeat_open_alert_count }}<br>"
        "<strong>Repeat-open alerts for this contact (total):</strong> {{ enrolled_object.repeat_open_alert_total }}</p>"
        "<p><a href=\"" + RECORD_LINK + "\">Open the contact record in HubSpot</a></p>"
        "<p style=\"color:#666;font-size:12px\">Sent by the workflow \"" + WORKFLOW_NAME + "\". "
        "Each email alerts once per contact.</p>"
    )
    return {
        "actionId": action_id,
        "type": "SINGLE_CONNECTION",
        "actionTypeId": "0-8",
        "actionTypeVersion": 0,
        "fields": {"user_ids": EMAIL_USER_IDS, "subject": subject, "body": body},
        "connection": {"edgeType": "STANDARD", "nextActionId": next_id},
    }


def is_notification(action):
    return action.get("actionTypeId") in ("0-8", "1-179507819")


def enrollment_criteria(list_filter_style):
    """Event trigger 'Opened email', re-enrolling on every open, optionally limited to one list.
    list_filter_style: 'nested' puts the list condition inside the event branch; 'none' omits it."""
    event_branch = {
        "filterBranches": [],
        "filters": [],
        "eventTypeId": "4-666440",
        "operator": "HAS_COMPLETED",
        "filterBranchType": "UNIFIED_EVENTS",
        "filterBranchOperator": "AND",
    }
    if ENROLL_LIST_ID and list_filter_style == "nested":
        event_branch["filterBranches"] = [{
            "filterBranches": [],
            "filters": [{"listId": ENROLL_LIST_ID, "operator": "IN_LIST", "filterType": "IN_LIST"}],
            "filterBranchType": "AND",
            "filterBranchOperator": "AND",
        }]
    return {
        "type": "EVENT_BASED",
        "shouldReEnroll": True,
        "eventFilterBranches": [event_branch],
        "listMembershipFilterBranches": [],
    }


def list_gate_action(next_id):
    """First step: branch 'is the contact in the list?'; everyone else exits immediately.
    (HubSpot's API rejects a list condition inside an event trigger, so the gate is a branch.)"""
    return {
        "actionId": "5",
        "type": "LIST_BRANCH",
        "listBranches": [{
            "filterBranch": {
                "filterBranches": [{
                    "filterBranches": [],
                    "filters": [{"listId": ENROLL_LIST_ID, "operator": "IN_LIST", "filterType": "IN_LIST"}],
                    "filterBranchType": "AND",
                    "filterBranchOperator": "AND",
                }],
                "filters": [],
                "filterBranchType": "OR",
                "filterBranchOperator": "OR",
            },
            "connection": {"edgeType": "STANDARD", "nextActionId": next_id},
        }],
        "defaultBranchName": "Not in list",
    }


def build_flow(source, list_filter_style="nested", list_gate=False):
    actions = [
        custom_code_action(source, "2"),
        {
            "actionId": "2",
            "type": "STATIC_BRANCH",
            "inputValue": {"type": "OBJECT_PROPERTY", "propertyName": "repeat_open_alert_pending"},
            "staticBranches": [{
                "branchValue": "true",
                "operator": "IS_EQUAL_TO",
                "connection": {"edgeType": "STANDARD", "nextActionId": "3"},
            }],
        },
        notification_action("3", "4"),
        {
            "actionId": "4",
            "type": "SINGLE_CONNECTION",
            "actionTypeId": "0-5",
            "actionTypeVersion": 0,
            "fields": {"property_name": "repeat_open_alert_pending",
                       "value": {"type": "STATIC_VALUE", "staticValue": "false"}},
        },
    ]
    start = "1"
    if list_gate and ENROLL_LIST_ID:
        actions.insert(0, list_gate_action("1"))
        start = "5"
    return {
        "isEnabled": False,
        "flowType": "WORKFLOW",
        "name": WORKFLOW_NAME,
        "type": "CONTACT_FLOW",
        "objectTypeId": "0-1",
        "startActionId": start,
        "nextAvailableActionId": "6",
        "canEnrollFromSalesforce": False,
        "enrollmentCriteria": enrollment_criteria(list_filter_style),
        "actions": actions,
    }


def main():
    token = load_env()["HUBSPOT_TOKEN"]
    source = open(os.path.join(HERE, "repeat-open-alert.js"), encoding="utf-8").read()
    if len(sys.argv) > 1:
        flow_id = sys.argv[1]
        status, flow = call(token, "GET", f"/automation/v4/flows/{flow_id}")
        if status != 200:
            print("GET failed", status, json.dumps(flow)[:800]); sys.exit(1)
        fresh = notification_action("3", "4")
        for a in flow["actions"]:
            if a.get("type") == "CUSTOM_CODE":
                a["sourceCode"] = source
            elif is_notification(a):
                nxt = a.get("connection", {}).get("nextActionId", "4")
                a.update({k: v for k, v in fresh.items() if k not in ("actionId", "connection")})
                a["connection"] = {"edgeType": "STANDARD", "nextActionId": nxt}
        status, res = call(token, "PUT", f"/automation/v4/flows/{flow_id}", flow)
        print("PUT", status, "revision", res.get("revisionId"), res.get("message", ""))
        if status >= 300: print(json.dumps(res, indent=1)[:3000])
        return
    for style, gate in (("none", True),):
        status, res = call(token, "POST", "/automation/v4/flows", build_flow(source, style, gate))
        print(f"POST (list filter style={style}, gate={gate}) ->", status)
        if status < 300:
            print("Created workflow id:", res.get("id"))
            print("URL: https://app.hubspot.com/workflows/" + PORTAL + "/platform/flow/" + str(res.get("id")) + "/edit")
            return
        print(json.dumps(res, indent=1)[:1500])


if __name__ == "__main__":
    main()
