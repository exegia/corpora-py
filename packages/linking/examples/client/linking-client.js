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