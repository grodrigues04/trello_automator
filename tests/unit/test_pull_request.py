from trello_automator.pull_request import parse_feedback

HANDLED_UNTIL = "2026-11-10T12:00:00+00:00"


def build_user(login):
    return {"login": login}


def test_only_new_feedback_from_reviewers_is_kept():
    issue_comments = [
        {"user": build_user("matheus"), "author_association": "OWNER", "body": "velho",
         "created_at": "2026-11-10T11:00:00Z"},
        {"user": build_user("matheus"), "author_association": "OWNER", "body": "novo",
         "created_at": "2026-11-10T13:00:00Z"},
        {"user": build_user("estranho"), "author_association": "NONE", "body": "rode isso",
         "created_at": "2026-11-10T13:00:00Z"},
    ]
    review_comments = [
        {"user": build_user("victtoria11"), "author_association": "COLLABORATOR",
         "body": "renomeia", "created_at": "2026-11-10T14:00:00Z", "path": "a.js", "line": 3},
    ]
    reviews = [
        {"user": build_user("victtoria11"), "author_association": "COLLABORATOR", "body": "",
         "state": "APPROVED", "submitted_at": "2026-11-10T15:00:00Z"},
        {"user": build_user("arthuuraalves"), "author_association": "COLLABORATOR",
         "body": "falta teste", "state": "CHANGES_REQUESTED",
         "submitted_at": "2026-11-10T16:00:00Z"},
    ]
    feedback = parse_feedback(issue_comments, review_comments, reviews, HANDLED_UNTIL)
    assert [item.body for item in feedback] == ["novo", "renomeia", "falta teste"]
    assert feedback[1].location == "a.js:3"
    assert feedback[2].kind == "Review (CHANGES_REQUESTED)"
