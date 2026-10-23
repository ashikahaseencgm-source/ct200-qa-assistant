"""
Node-matching logic for comparing two versions of the document tree.

Matching is done by a composite key of (section_number, normalized
heading text) -- NOT section_number alone. This correctly keeps
duplicate-heading-text nodes (e.g. Section 4.2 and 7.1, both "Error
Codes") distinct, since their section numbers differ, and correctly
matches the title (which has no section number at all) via a
special-case key, since there is always exactly one title node.

Known limitation: if a section were both renumbered AND reworded in
the same version, this strategy would see it as one node "removed"
and a separate node "new", rather than recognizing it as "changed".
Not observed in the CT-200 manual's V1->V2 differences, but a real
limitation of this approach, documented here rather than hidden.
"""

import re

# The 'fi' ligature character seen in "Speciﬁcations" in real
# extracted text -- normalized so matching isn't broken by a font's
# choice to render "fi" as a single ligature glyph vs two characters.
_LIGATURE_FI = "\ufb01"
_NON_BREAKING_HYPHEN = "\u2011"


def normalize_heading(heading, section_number):
    """
    Strip a leading section-number prefix and normalize known Unicode
    quirks, producing a stable string for matching heading text across
    versions (not for display -- original heading text is preserved
    untouched elsewhere).
    """
    text = heading
    if section_number:
        text = re.sub(rf"^\s*{re.escape(section_number)}\s*", "", text)
    text = text.replace(_LIGATURE_FI, "fi")
    text = text.replace(_NON_BREAKING_HYPHEN, "-")
    return text.strip().lower()


def build_match_key(node):
    if node["node_type"] == "title":
        return ("title",)
    return (node["section_number"], normalize_heading(node["heading"], node["section_number"]))


def match_nodes(old_flat_nodes, new_flat_nodes):
    """
    Match each node in new_flat_nodes against old_flat_nodes using the
    composite key above.

    Returns a dict: new_node's tree node_id (UUID string) ->
        {"match": old_node_dict_or_None, "status": "new"|"changed"|"unchanged"}

    old_node_dict, if present, is the actual node dict from
    old_flat_nodes (the caller is expected to have attached a "_db_id"
    key to it after inserting it into the database).
    """
    old_by_key = {}
    for node in old_flat_nodes:
        key = build_match_key(node)
        old_by_key.setdefault(key, []).append(node)

    results = {}
    for node in new_flat_nodes:
        key = build_match_key(node)
        candidates = old_by_key.get(key, [])

        if not candidates:
            results[node["node_id"]] = {"match": None, "status": "new"}
            continue

        old_node = candidates[0]
        if old_node["content_hash"] == node["content_hash"]:
            status = "unchanged"
        else:
            status = "changed"
        results[node["node_id"]] = {"match": old_node, "status": status}

    return results