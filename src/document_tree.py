
import hashlib
import re
import uuid


def generate_content_hash(text: str) -> str:
    """Generate a SHA-256 hash for normalized text content."""
    normalized_text = " ".join(text.split())
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def extract_section_number(heading: str) -> str | None:
    """Extract a section number from a heading."""
    match = re.match(r"^\s*(\d+(?:\.\d+)*)\.?\s+", heading)
    return match.group(1) if match else None


def create_node(
    heading: str,
    body: str = "",
    level: int = 1,
    parent_id: str | None = None,
) -> dict:
    """Create a document node with identity and hierarchy fields."""
    return {
        "node_id": str(uuid.uuid4()),
        "heading": heading,
        "section_number": extract_section_number(heading),
        "level": level,
        "body": body,
        "parent_id": parent_id,
        "children": [],
        "content_hash": generate_content_hash(body),
    }


def build_tree(nodes: list[dict]) -> list[dict]:
    """Connect nodes and reject missing parent references."""
    node_lookup = {node["node_id"]: node for node in nodes}
    
    # Detect circular parent references.
    for node in nodes:
        visited = set()
        current = node

        while current["parent_id"] is not None:
            parent_id = current["parent_id"]

            if parent_id in visited:
                raise ValueError(
                    f"Circular parent relationship detected "
                    f"for node '{node['heading']}'."
                )

            visited.add(parent_id)

            if parent_id not in node_lookup:
                break

            current = node_lookup[parent_id]


    if len(node_lookup) != len(nodes):
        raise ValueError("Duplicate node IDs found.")

    # Check parent references before building the tree.
    for node in nodes:
        parent_id = node["parent_id"]

        if parent_id and parent_id not in node_lookup:
            raise ValueError(
                f"Missing parent '{parent_id}' "
                f"for node '{node['heading']}'."
            )

        if parent_id == node["node_id"]:
            raise ValueError("A node cannot be its own parent.")

    # Clear existing children so repeated calls are safe.
    for node in nodes:
        node["children"] = []

    root_nodes = []

    for node in nodes:
        parent_id = node["parent_id"]

        if parent_id:
            node_lookup[parent_id]["children"].append(node)
        else:
            root_nodes.append(node)

    return root_nodes



if __name__ == "__main__":
    print("Content hash test:")
    print(generate_content_hash("Battery life is 300 cycles."))

    print("\nSection number tests:")
    test_headings = [
        "1. Device Overview",
        "1.1 Intended Use",
        "2.1.1 Battery Life",
        "Data Export",
    ]

    for heading in test_headings:
        print(f"{heading} -> {extract_section_number(heading)}")

    print("\nDocument node test:")
    node = create_node(
        heading="1.1 Intended Use",
        body="The device measures blood pressure.",
        level=2,
        parent_id="section-1",
    )

    print("Node ID:", node["node_id"])
    print("Heading:", node["heading"])
    print("Section number:", node["section_number"])
    print("Level:", node["level"])
    print("Parent ID:", node["parent_id"])
    print("Content hash:", node["content_hash"])
    print("Children:", node["children"])

    print("\nParent-child tree test:")

    parent = create_node(
        heading="1. Device Overview",
        level=1,
    )

    child = create_node(
        heading="1.1 Intended Use",
        level=2,
        parent_id=parent["node_id"],
    )

    tree = build_tree([parent, child])

    print("Root heading:", tree[0]["heading"])
    print("Child heading:", tree[0]["children"][0]["heading"])
    print(
        "Child parent ID matches:",
        tree[0]["children"][0]["parent_id"] == tree[0]["node_id"],
    )

    
    print("\nMissing-parent validation test:")

    orphan = create_node(
        heading="1.1 Intended Use",
        level=2,
        parent_id="missing-parent",
    )

    try:
        build_tree([orphan])
    except ValueError as error:
        print("Validation passed:", error)
    else:
        print("ERROR: Missing parent was not detected.")
    
    print("\nCircular relationship test:")

    node_a = create_node(
        heading="1. Device Overview",
        level=1,
    )

    node_b = create_node(
        heading="1.1 Intended Use",
        level=2,
        parent_id=node_a["node_id"],
    )

    # Create a cycle: A is made a child of B.
    node_a["parent_id"] = node_b["node_id"]

    try:
        build_tree([node_a, node_b])
    except ValueError as error:
        print("Cycle detection passed:", error)
    else:
        print("ERROR: Circular relationship was not detected.")


    

