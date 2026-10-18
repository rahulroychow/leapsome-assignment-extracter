# Leapsome assignment extracter

Review and approve open-ended learning responses that people submitted to you in Leapsome, from a small local Streamlit app.

## Background: what this is and how it works

Leapsome is where we do training courses. It's good for doing a course, but not for working through a pile of submissions you have to review. This tool reads those submissions and shows them in a nicer screen, grouped by assessment, with an Approve button. It works, but it relies on Leapsome's private, undocumented web API.

When you use Leapsome in your browser, the page keeps asking Leapsome's servers questions behind the scenes ("what has this person completed?") and draws the answers. This tool asks **the same questions, using the same login proof your browser uses**.

```
 You ──▶ Streamlit app (app.py) ──▶ helper code (leapsome_api.py) ──▶ Leapsome servers
         the screen you click on     knows how to talk to Leapsome       the real data
                                                                              │
                                     attachments come from a separate  ◀──────┘
                                     file store (Amazon S3), via a
                                     temporary link Leapsome hands out
```

| Piece | What it is |
|---|---|
| **Bearer token** | A long string that proves you're logged in. It lasts about an hour. |
| `capture_token.py` | Reads the token the Leapsome page already keeps in Chrome (see "How the token works" below). |
| `leapsome_api.py` | The "translator": builds each request the way Leapsome expects and tidies up the replies. |
| `app.py` | The Streamlit screen. It runs on your own laptop; nothing is hosted anywhere. |

The Leapsome calls it makes (these are the only endpoints the tool uses):

| What it does | Reads or changes data? |
|---|---|
| **Responses to review**: answers other people submitted that are waiting on you. | Read only |
| **Attachment download**: asks Leapsome for a temporary link to a file, then downloads it. | Read only |
| **Approval**: marks a submission as approved. | **Changes data** |

All three use the same login proof. Two extra "who am I" headers are needed, and they're read straight out of the token.

## Setup

Requires Python 3.9+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## How the token works

There is nothing to copy or configure. The Leapsome web app keeps its current bearer token in Chrome's localStorage (key `leapsomeToken`), and Chrome stores that as plain files on disk. `capture_token.py` scans Chrome's Local Storage files and picks out the Leapsome token by its contents (other sites' tokens are ignored). It doesn't use cookies or the macOS Keychain, and it doesn't start a browser.

- Just be logged in to https://www.leapsome.com in Chrome.
- The token lasts about an hour, and Leapsome's page refreshes it while a tab is open. If the newest token has expired (no Leapsome tab was open for a while), the app shows an **Open Leapsome in Chrome** button. It opens the page in the background, waits for the token to refresh, and carries on.
- macOS only (it looks in `~/Library/Application Support/Google/Chrome`).

## Run the Streamlit app

```bash
streamlit run app.py
```

The app is a single page, **Responses to review**. It loads automatically when it opens, and **Refresh** reloads it.

- Responses are grouped by assessment. Each assessment is a collapsible section showing how many responses it has and how many are pending, and it opens by default when something is waiting on you. Versions of the same assessment are grouped together.
- Inside a group, each row shows who sent it, the status and an answer preview. Open a row's **Details** for the full answer and attachments (images preview in place).
- Rows with status `pendingApproval` have an **Approve** button (`POST /api/learning/responses/openEndedQuestion/approval`). It asks for confirmation first, and it changes the submission in Leapsome.
- Search by assessment, submitter or answer text, and filter by status.
- **Advanced: API filters** takes a JSON object for the review endpoint (`POST /api/learning/responses/openEndedQuestion`). It defaults to `{}`, which returns everything. The filter keys the API accepts aren't documented here.

## Findings

- **Attachments take two steps.** The list only says "there's a file called X". Getting the file means asking for a short-lived link and then downloading from it, which is why the app has a **Load** button per file.
- **Approving returns an empty reply** on success, which the code has to treat as success.
- **The token only lasts about an hour** and only refreshes while a Leapsome tab is open (see "How the token works").

## Risks and limits

1. **It's an unofficial back door.** Leapsome could change these private endpoints at any time and the tool would break. There's no promise of support or stability.
2. **Terms of use.** It only acts on your own account's data, but scripting around the website rather than an official integration may not be something Leapsome or company policy is happy with. Worth a quick check before anyone relies on it.
3. **The token is a password.** Anyone with it can act as you for an hour, including approving submissions. The app keeps it in memory only and never writes it to a file. Don't paste it into chats, tickets or commits.
4. **Approve changes real data.** It's the only write action and it's guarded by a confirm step. It was tested live once by hand and otherwise against a mocked API.
5. **There is no Reject.** The real "reject" request was never captured, and guessing at a data-changing call is a bad idea.
6. **The review filter box is a black box.** It accepts raw JSON, but only the empty `{}` ("everything") is known to work. Which filters Leapsome supports isn't known.
7. **Tested on one account** with a handful of review items, so odd cases (very long lists, other file types, other statuses) haven't been seen.
