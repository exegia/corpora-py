---
title: Reference linking client quick start
description: Small steps and browser examples for selecting, saving and opening reference links.
tags: [references, client, quickstart]
---

# Make a link, one small step at a time

**Your first goal: select some words → save a link → open its exact destination.**

Think of a reference as a bookmark with a string attached.
One end points to the words you selected. The other end points to a passage or book.

You do not need paragraph IDs or sentence numbers.

## Pick your starting point

- **I want to see it work first:** run the small demo below.
- **My server is ready:** jump to [Step 1](#step-1-get-the-four-things-your-app-needs).
- **My server is not ready:** use the [server checklist](#before-you-connect-a-client).

## Try the browser playground

From the repository root:

```bash
uv run python packages/linking/examples/client/server.py
```

Open **http://127.0.0.1:8787**. Click **Select the example passages**,
then **Preview selections**, **Save link**, and **Open destination**.
Choose Reviewer to test approval. **Test stale selection** checks that a changed
version is rejected. The page uses temporary SQLite storage and synthetic demo
roles; it does not connect to live Supabase.

Stop it with Ctrl+C. See the [playground README](../../../packages/linking/examples/client/README.md).

## See it work first — no server needed

From the `corpora-py` repository:

```bash
uv run python packages/linking/examples/manual_link.py
```

This Python demo makes a manual link, retrieves its selected words, and checks
that a changed document cannot silently become the destination.

**Done when:** the command finishes without an error. This is an offline demo;
it does not save anything to Supabase.

## Before you connect a client

The browser talks to the Python server. The server talks to the working database.

```text
Your reader app → /linking API → working references + trusted documents
```

Give the backend developer this checklist:

- [ ] Enable the linking service with a trusted inventory of documents and passages.
- [ ] Provision the proposed schema in an approved development database.
- [ ] Configure JWT verification and valid user sessions.
- [ ] Give the user a space membership and access to BOTH linked resources.
- [ ] Give creators `contribute`; give reviewers `review`.
- [ ] Serve the client the exact document text and its version information.
- [ ] Permit the client origin in the app's CORS configuration, if origins differ.

The schema has **not** been deployed to live Supabase. Enabling the service does
not create tables or grant access. The server setup is explained in
[production integration](../production.md#server-composition).

Keep database credentials and service-role keys on the server. The client uses
the reader's access token.

**Done when:** a signed-in reader can call `/linking/{space_id}/retrieve` for a
known, allowed selection. A `503` means the backend needs attention.

## Step 1: Get the four things your app needs

| Thing | What it means | Where it comes from |
|---|---|---|
| API URL | The Python server's address | Your app configuration |
| Space ID | The workspace containing the links | Your server |
| Access token | Who is signed in right now | Your sign-in system |
| Document snapshot | Exact text + document/version IDs + stream name | Your authorized document service |

The linking API does not currently provide a document-list or snapshot-download
route. Your app's document service supplies those. It must return the same text
that the linking server knows. A displayed excerpt alone cannot supply offsets
for the full stream.

A snapshot looks like this. These IDs are examples, **not real library IDs**:

```json
{
  "endpoint": {
    "work_id": "example-essay",
    "edition_id": "example-edition",
    "package_id": "example-package",
    "revision": "example-immutable-version",
    "document_id": "chapter-1",
    "locators": []
  },
  "stream_id": "body",
  "text": "Before. The linked passage. After."
}
```

Copy identity fields from the server. Do not make up a revision or change it to
`latest`. The version tells us which exact copy of the document was selected.

**Done when:** your app has the real snapshot and the signed-in user's session.

## Step 2: Add a tiny API helper

Put this in `linking-client.js`. It works with plain JavaScript, React, Vue, or
another browser app. `getAccessToken()` should return the current session token.

```javascript
export function makeLinkClient({apiUrl, spaceId, getAccessToken}) {
  async function request(path, body) {
    const token = await getAccessToken();
    if (!token) throw new Error("Please sign in.");

    const response = await fetch(
      `${apiUrl.replace(/\/$/, "")}/linking/${encodeURIComponent(spaceId)}${path}`,
      {
        method: body === undefined ? "GET" : "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      },
    );
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.detail || "Could not finish this step.");
      error.status = response.status;
      throw error;
    }
    return result;
  }

  return {
    save: (reference, expectedVersion = null) => request("/references", {
      reference,
      expected_version: expectedVersion,
      reason: "Reader linked a selection",
    }),
    latest: async (id) => {
      const result = await request(`/references/${encodeURIComponent(id)}`);
      return result.history.at(-1);
    },
    retrieve: (endpoint) => request("/retrieve", endpoint),
    decide: (id, action, version, reason) => request(
      `/references/${encodeURIComponent(id)}/${action}`,
      {expected_version: version, reason},
    ),
  };
}
```

Connect it to your existing sign-in system:

```javascript
import {makeLinkClient} from "./linking-client.js";

// Supply these from YOUR app's configuration and authentication code.
const links = makeLinkClient({apiUrl, spaceId, getAccessToken});
```

**Done when:** `await links.retrieve(knownEndpoint)` returns `{text: "…"}`.

## Step 3: Turn selected words into an address

Start with a **read-only textarea containing the complete snapshot text**.
This is the easiest first implementation. A rich HTML/PDF/EPUB reader uses the
format-specific helpers further down.

Browsers count some emoji as two units. Python counts them as one character.
This helper translates browser offsets before saving them.

Add this to `linking-client.js`:

```javascript
function scalarOffset(text, utf16Offset) {
  if (!Number.isInteger(utf16Offset) || utf16Offset < 0 || utf16Offset > text.length) {
    throw new Error("Selection is outside the text.");
  }
  const before = text.charCodeAt(utf16Offset - 1);
  const after = text.charCodeAt(utf16Offset);
  if (before >= 0xD800 && before <= 0xDBFF && after >= 0xDC00 && after <= 0xDFFF) {
    throw new Error("Please select the whole emoji.");
  }
  return Array.from(text.slice(0, utf16Offset)).length;
}

export function selectedEndpoint(snapshot, textarea) {
  if (textarea.value !== snapshot.text) {
    throw new Error("Reload the exact document text before linking.");
  }
  const characters = Array.from(snapshot.text);
  const start = scalarOffset(snapshot.text, textarea.selectionStart);
  const end = scalarOffset(snapshot.text, textarea.selectionEnd);
  if (start >= end) throw new Error("Select some words first.");

  return {
    ...snapshot.endpoint,
    locators: [{
      kind: "text",
      stream_id: snapshot.stream_id,
      normalization: "preserve",
      start,
      end,
      exact: characters.slice(start, end).join(""),
      prefix: characters.slice(Math.max(0, start - 32), start).join(""),
      suffix: characters.slice(end, end + 32).join(""),
    }],
  };
}
```

`start` includes the first selected character. `end` stops just after the last.
Spaces, punctuation and line breaks count. Keep the text unchanged: no trimming,
case changes, or Unicode normalization. Textareas can change line endings;
the equality check stops that from making a wrong link.

**Done when:** selecting `The linked passage` produces those exact words in `exact`.

## Step 4: Pick the other end

For your first version, use two textareas: source document and destination document.
Each gets its own full server snapshot.

```javascript
import {selectedEndpoint} from "./linking-client.js";

const source = selectedEndpoint(sourceSnapshot, sourceTextarea);
const target = selectedEndpoint(targetSnapshot, targetTextarea);

// Preview BOTH ends before saving.
const sourcePreview = await links.retrieve(source);
const targetPreview = await links.retrieve(target);
```

Display the previews as text, for example with `element.textContent`.

For **an entire work**, the target can instead be:

```javascript
const target = {work_id: chosenWork.work_id, locators: []};
```

Use a real work ID from your catalog. Your app opens the work through its own
library route. `/retrieve` retrieves exact selections; it does not return a whole
book for a work-only target.

For **a Bible verse**, your verse picker can supply a citation request:

```javascript
const target = {
  work_id: chosenBibleBook.work_id,
  locators: [{
    kind: "citation",
    value: "John 3:16",
    profile: citationContext.profile,
    scheme_id: citationContext.scheme_id,
    scheme_version: citationContext.scheme_version,
  }],
};
```

Your server supplies the book ID and numbering context. It needs an explicit
passage mapping to find the exact verse. Typing `John 3:16` alone does not prove
which edition or passage to retrieve. Resolve it in Step 6 before previewing it.

**Done when:** both ends are selected, or you have deliberately chosen a work/verse.

## Step 5: Save the link

Create the ID once for this draft. Keep this same draft if a network request
fails; do not allocate another ID just because the Save button was pressed again.
Disable Save while a request is running.

```javascript
const draft = {
  id: crypto.randomUUID(),
  source,
  target,
  relationship: "core:cites",
  provenance: {
    origin: "manual",
    agent_id: "client-placeholder",
    method: "reader-selection",
  },
};

const saved = await links.save(draft);
let referenceId = saved.reference.id;
let version = saved.version;
```

Use `core:cites` for a citation. Your app can agree on another relationship name,
such as `app:related`, for a reader's related-passage link.

The server replaces new-link provenance with the signed-in actor. The placeholder
is required by the input model; it is not trusted as the creator identity.

Keep the returned ID and version in your app's link state. There is currently no
“list all references” route; your application needs its own authorized link index
for loading them when the reader returns.

**Done when:** you can show **“Link saved — waiting for review.”**

## Step 6: Check the destination and open it

Resolve the saved request, then read its newest version:

```javascript
await links.decide(referenceId, "resolve", version, "Check selected destination");
let current = await links.latest(referenceId);
version = current.version;

if (current.reference.resolution === "resolved") {
  // Work-only destinations use your app's library navigation instead.
  if (current.reference.target.locators.length > 0) {
    const result = await links.retrieve(current.reference.target);
    destinationPreview.textContent = result.text;
  }
} else {
  statusLabel.textContent = "This link needs a choice or a fresh selection.";
}
```

| Result | Show the reader |
|---|---|
| `resolved` | “Destination found.” |
| `ambiguous` | “More than one match. Please choose.” |
| `unresolved` | “We cannot verify this destination yet.” |
| `unavailable` | “The required document is not available.” |

A successful HTTP response does not always mean resolution succeeded. Read the
stored `resolution`. Candidate choices and diagnostics are in the latest revision's
`validation.target`. Only offer verified candidates; do not pick the first one.
Save an explicit choice as an edit using `links.save(updatedReference, version)`,
then resolve again. Refresh the current version after every change.

**Done when:** clicking your link shows the exact selected destination, or an honest
message asking for help.

## Step 7: Add review when you need it

A reviewer signs in with `review` permission, loads the latest revision, checks
both ends, and presses Approve:

```javascript
const current = await links.latest(referenceId);
await links.decide(referenceId, "approve", current.version, "Checked both selections");
```

Keep three separate labels in your app:

| Label | Question it answers |
|---|---|
| Resolution | Can we locate the destination? |
| Review | Has a person approved the link? |
| Publication | Has this version been marked published? |

Saving does not approve. Approval does not publish. Editing makes the link need
review again. Published links must be withdrawn and reopened before editing.

For publishing into C-USX, use the separate [export/publication workflow](../production.md#http-workflows).
Export prepares an artifact; it does not send it anywhere. An acknowledgment is
separate from a provider's delivery receipt.

**Done when:** an approved link displays its review status separately from resolution.

## Add a rich reader later

Get the two-textarea path working first. Then replace its selection helper.

| Reader | Selection path | Important detail |
|---|---|---|
| HTML | `captureSelection(document)` → POST `/browser-selection` | Browser and server text-node trees must match |
| PDF | PyMuPDF native text + glyph quads | One-based pages; top-left unrotated CropBox coordinates in points |
| EPUB | Server-generated/verified CFI range | Use the pinned resource DOM; translate UTF-16 offsets |
| C-USX | Advertised structural anchor or paired boundary | Anchor must exist uniquely in that version |

For HTML, copy [browser_selection.js](../../../packages/linking/examples/browser/browser_selection.js)
into your client assets. Capture the document **inside the reader's same-origin
iframe**, not the page containing your toolbar and other app text:

```javascript
const capture = captureSelection(readerIframe.contentDocument);
// POST this body to /linking/{space_id}/browser-selection with the reader's token.
const body = {original: originalEndpoint, asset_id: originalAssetId, ...capture};
```

The response contains `{endpoint, text}`. Use its `endpoint` as the source or target
in Step 5. A parser mismatch or modified DOM rejects; ask the reader to reload.
The initial bridge accepts text-node endpoints. It is not a general browser layout
or PDF/EPUB viewer-selection SDK. Adapter functions and supported format limits
are listed in [native adapters](../production.md#exact-native-adapters).

## Automatic citations use the same saved links

The conversion job calls `/conversion-events` with trusted original/converted
identities and a durable event ID. The server detects supported Bible citations,
retains original-file mappings and saves pending references. Retries reuse IDs.
Your app displays those references through the same review/open flow above.

Scholarly conversion uses a configured recognizer and `/scholarly-conversion-events`.
Unknown works stay as discovery records. Reviewers identify or choose a work through
`/discoveries/{id}/{identify,select}` before resolving its passage. No match means
“needs identification,” never an invented book.

## When a step gets stuck

| HTTP code | What to do |
|---|---|
| `401` | Sign in again or refresh the session token |
| `403` | Ask for the required space permission and resource access |
| `404` | Check the reference ID and space |
| `409` | Reload the latest version; let the reader reconcile their edit |
| `422` | Recheck the selection, document version and allowed transition |
| `503` | Ask the backend developer to check service setup and dependencies |

Keep the reader's draft after an error. Show a Retry or Reselect button as
appropriate. Do not silently move the link to words that merely look similar.

## Your first version is finished when…

- [ ] A reader can select source and destination words.
- [ ] The app previews both exact selections.
- [ ] Save returns an ID and version.
- [ ] Opening the link retrieves the exact destination.
- [ ] Changing document text makes the stale link fail visibly.
- [ ] Ambiguous destinations ask for a choice.
- [ ] A second editor's change produces a reload/reconcile message.
- [ ] Review and publication have their own status labels.

For the complete server contract, keep [production integration](../production.md)
nearby. For a local full-workflow demo, see [the walkthrough](../end-to-end.md).
