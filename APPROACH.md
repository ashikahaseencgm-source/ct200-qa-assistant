# Approach Document — CT-200 QA Assistant

**Project:** CT-200 QA Assistant  
**Purpose:** Convert PDF product manuals into a structured, version-aware QA testing system  
**Technology stack:** Python, PyMuPDF, FastAPI, SQLAlchemy, SQLite, Google Gemini, pytest  
**Document type:** Technical implementation approach and design decisions

---

## 1. Project Overview

### 1.1 Problem statement

The CT-200 QA Assistant was developed to transform two versions of a fictional blood pressure monitor product manual into a structured, searchable document system that can support QA test-case generation.

The system needed to:

1. Extract meaningful content from PDF manuals while preserving page information, headings, tables, and lists.
2. Reconstruct the extracted content into a hierarchical document tree.
3. Store multiple document versions without confusing their individual contents.
4. Identify new, changed, unchanged, and removed sections between versions.
5. Allow users to browse document nodes and create named selections.
6. Generate QA test-case ideas from selected document content using an LLM.
7. Identify whether previously generated test cases may be stale after their source documentation changes.
8. Expose these capabilities through REST APIs.

### 1.2 Development philosophy

The implementation followed an incremental approach rather than building the complete application immediately.

The guiding principle was:

**Inspect the documents → Build the parser → Validate the tree → Implement versioning → Add database persistence → Build APIs → Integrate the LLM → Validate the complete workflow.**

This order was important because an API or AI model cannot compensate for incorrectly extracted source information. If a specification is missing or attached to the wrong section, subsequent version comparisons and generated test cases may also be incorrect.

---

## 2. End-to-End Architecture

The system consists of five major layers.

### 2.1 Architecture diagram

```text
             CT-200 PDF Manuals
                 V1 and V2
                     |
                     v
          PDF Extraction Layer
             pdf_extractor.py
                     |
                     v
         Structured Content Blocks
        Headings, Text, Tables, Lists
                     |
                     v
          Document Tree Builder
             tree_builder.py
                     |
                     v
          Version Matching Layer
              versioning.py
                     |
                     v
           SQLAlchemy + SQLite
        Documents, Versions, Nodes,
               Selections
                     |
          +----------+-----------+
          |                      |
          v                      v
      Browse API            Selection API
          |                      |
          |                      v
          |               Gemini Integration
          |                 llm_client.py
          |                      |
          |                      v
          |                Test-Case Store
          |                test_cases_store.json
          |                      |
          +----------+-----------+
                     |
                     v
               Staleness API
                     |
                     v
        Test Cases + Source-Change Status
```

### 2.2 Main components

| Component | Responsibility |
|---|---|
| `pdf_extractor.py` | Extracts and classifies content from PDFs. |
| `tree_builder.py` | Reconstructs a hierarchical document structure. |
| `versioning.py` | Matches nodes across document versions and determines their change status. |
| `models.py` | Defines the database entities and relationships. |
| `ingest_versions.py` | Processes document versions and populates the database. |
| FastAPI application | Exposes browsing, searching, selection, generation, and staleness endpoints. |
| `llm_client.py` | Communicates with Google Gemini and handles generation errors. |
| `test_cases_store.json` | Stores generated test cases and their source-node hashes. |
| `pytest` test suite | Validates extraction, tree construction, hashing, versioning, and API behavior. |

The SQLite database is used for structured relational data. Generated test cases are stored separately in JSON, which acts as the assignment's lightweight NoSQL-style store.

---

## 3. Development Process

### Phase 1 — Inspect the PDFs before writing the parser

**Objective:** Understand the actual structure and irregularities of both manuals before implementing extraction logic.

The two source files were:

- `data/ct200_manual.pdf` — Version 1
- `data/ct200_manual_v2.pdf` — Version 2

The manuals were inspected manually, section by section, to identify differences in formatting, ordering, and content.

#### Findings from the actual PDFs

**1. Tables**

- Section 2.1 contains a General Specifications table.
- Section 4.2 contains an Error Codes table.
- Version 1 includes error codes E1–E5.
- Version 2 includes E1–E6 and changes the E3 timing value from 2 seconds to 1.5 seconds.

These tables needed to remain structured rather than being treated as ordinary paragraphs.

**2. Numbered classification list**

Section 3.3 contains blood pressure classifications, including Normal, Elevated, Hypertension Stage 1, Stage 2, and crisis-related categories.

The parser needed to preserve the distinction and order of the list items.

**3. Out-of-order section headings**

In Version 1, Section 3.4, “Auto Shutoff,” appears physically before Section 3.3, “Result Display and Classification.”

The logical tree therefore could not rely solely on physical PDF order.

**4. Different page layouts**

Section 4 appears at different page and block positions between the two versions. A page-layout change should not automatically count as a content change.

**5. Continuation on a nearly empty page**

Version 2 has a seventh page containing approximately 81 characters continuing Section 8.1. This page does not introduce a new heading and should not become a separate section.

#### Why this phase mattered

These observations established the parser's requirements before code was written. They also prevented common mistakes, such as assuming that every page starts a new section or every heading appears in numerical order.

**Deliverable:** A clear understanding of the source PDFs, their content structure, and their meaningful differences.

### Phase 2 — Build the PDF extractor incrementally

**Objective:** Extract content blocks while retaining enough information to reconstruct the original document structure.

The extractor was developed in small, testable stages using PyMuPDF.

#### Implementation sequence

1. Extract raw text blocks with page and positional information.
2. Detect headings using formatting clues such as font size and boldness.
3. Identify tables as distinct content blocks.
4. Identify numbered lists as distinct content blocks.
5. Inspect the extracted output against the original PDFs.

Each stage was checked before adding the next.

#### Why classify blocks?

A PDF's raw text is not the same as a structured document. If all content is concatenated into one string, the system loses information about which text is a heading, which values belong to a table, and which items form a list.

The extractor therefore classifies content into meaningful block types, such as:

- Heading
- Body text
- Table
- List

Page and position information are retained as extraction metadata.

#### Validation approach

The extracted content was printed and manually compared with the PDF. This helped reveal formatting and Unicode issues that would otherwise be difficult to diagnose later.

**Deliverable:** A structured sequence of content blocks suitable for tree construction.

### Phase 3 — Reconstruct the hierarchical document tree

**Objective:** Convert the flat list of extracted blocks into a parent-child hierarchy.

The `tree_builder.py` component uses detected heading levels and section numbers to reconstruct relationships.

For example:

```text
CT-200 Manual
├── Section 1
├── Section 2
│   ├── Section 2.1
│   └── Section 2.2
├── Section 3
│   ├── Section 3.1
│   ├── Section 3.2
│   ├── Section 3.3
│   └── Section 3.4
└── Section 4
    ├── Section 4.1
    └── Section 4.2
```

The tree is based on the manual's logical section structure rather than blindly following physical page order.

For example, Section 3.3 must appear before Section 3.4 in the reconstructed hierarchy even when the PDF prints Section 3.4 first.

#### Why this matters

The tree enables the system to:

- Browse the document by section.
- Retrieve a node's parent and children.
- Reconstruct selected content in a meaningful order.
- Compare corresponding sections across versions.
- Supply relevant context to the LLM.

**Deliverable:** A hierarchical representation of the extracted manual.

### Phase 4 — Write tests before implementing versioning

**Objective:** Establish that extraction and tree construction work correctly before building features on top of them.

Unit tests were written for:

- Tree structure.
- Content hashing.
- Table extraction.
- List extraction.

This phase caught a content-hashing issue: two nodes with identical headings in different sections were not adequately distinguished in an early implementation.

The hashing logic was therefore reviewed so that section identity and relevant content could be represented more reliably.

#### Why this sequence was important

If the parser creates incorrect nodes, the version matcher may compare unrelated content. Testing the foundational components first reduces the chance of debugging multiple layers at once.

**Deliverable:** A tested parsing and tree-building foundation.

### Phase 5 — Implement version matching

**Objective:** Compare corresponding document nodes between Version 1 and Version 2.

Version matching was implemented only after the document tree and its tests were sufficiently reliable.

The matching logic identifies corresponding nodes and compares their content hashes.

The result can classify a node as:

- `baseline` — initial-version node.
- `new` — node introduced in a later version.
- `changed` — corresponding node whose content differs.
- `unchanged` — corresponding node whose content remains the same.
- `removed` — earlier-version node with no corresponding node in the later version.

The exact persisted status depends on whether the node is being represented as an initial baseline or a later-version comparison result.

#### Actual development issue: SQLite file locking

The initial runs of `ingest_versions.py` encountered:

```text
PermissionError: [WinError 32]
```

The script was attempting to delete and rebuild `ct200_qa.db`, but another process was holding the database file open.

The likely cause was a leftover Uvicorn process or a database viewer.

Closing the process holding the file resolved the issue. This was an environment/file-locking problem rather than a version-matching defect.

**Deliverable:** Version-aware nodes and change classifications.

### Phase 6 — Design the database and correct the selection schema

**Objective:** Persist documents, versions, tree nodes, and named selections.

The `models.py` component defines the SQLAlchemy data model.

The main entities are:

- `Document`
- `DocumentVersion`
- `Node`
- `Selection`
- `SelectionNode`

#### Initial schema mistake

The first version of `Selection` supported only one node per selection.

However, the assignment required users to submit a set of node IDs as a named selection. The schema was therefore redesigned to use a `SelectionNode` join table.

A selection can now contain multiple nodes, with each selected node associated with a specific document version.

#### Why the join table is necessary

A join table allows the system to represent a many-to-many-style selection relationship while preserving version information.

For example:

```text
Selection
└── SelectionNode
    ├── node_id
    └── version_id
```

This prevents a selection created against Version 1 from silently resolving to different content simply because Version 2 is ingested later.

#### Second database issue: stale schema

After the model was corrected, `POST /selections` still returned a `500 Internal Server Error`.

The problem was that the existing database had been created using the old schema. The database initialization function created missing tables but did not automatically alter existing tables to match the new model.

Re-running `ingest_versions.py` rebuilt the database using the corrected schema and resolved the issue.

**Deliverable:** A relational schema that supports versioned documents and multi-node selections.

### Phase 7 — Build and validate the Browse and Selection APIs

**Objective:** Expose document browsing and selection functionality before introducing the LLM.

FastAPI was used to provide REST endpoints.

The Browse API allows clients to inspect the document tree, retrieve node details, and search for relevant content.

The Selection API allows users to create named selections of document nodes.

#### Actual development issue: Uvicorn blocked the terminal

Requests initially failed with connection errors because the Uvicorn server and the API test commands were being run in the same PowerShell terminal.

When Uvicorn runs in the foreground, it occupies that terminal.

**Fix:** Use two terminals.

- Terminal 1 runs the API server.
- Terminal 2 sends API requests and inspects the responses.

#### Actual development issue: nested JSON appeared broken

PowerShell's default `Format-Table` output flattened or hid nested JSON structures. This made valid API responses appear incomplete.

The following command provided a more reliable inspection method:

```powershell
$response | ConvertTo-Json -Depth 10
```

This showed the nested response data correctly.

**Deliverable:** Validated Browse and Selection endpoints that work independently of the LLM.

### Phase 8 — Integrate Gemini and investigate the search bug

**Objective:** Generate structured QA test-case ideas from selected document content.

The LLM integration uses Google's Gemini API through the `google-genai` library.

The `llm_client.py` component handles the model request and its error conditions.

#### Prompt design

The selected document content is reconstructed from the selected nodes, including headings and body text, in tree order.

The prompt instructs Gemini to produce three to five QA test-case ideas based on the selected requirements and to return structured JSON rather than free-form prose.

Structured output makes it possible to validate, store, retrieve, and inspect the generated test cases.

#### Actual development issue: unavailable model

The first model name attempted was `gemini-2.0-flash`. It returned a `404 NOT_FOUND` response indicating that the requested model was no longer available for that API request.

The model configuration was updated. The error handling also demonstrated that a model failure could be surfaced to the API client instead of producing fabricated test cases.

#### Actual development issue: transient service unavailability

A Gemini request returned `503 UNAVAILABLE` during a period of high demand.

A retry succeeded. This showed why transient service errors should be handled separately from errors caused by invalid configuration or malformed requests.

#### Actual development issue: search missed words containing ligatures

The `/search` endpoint initially used lowercase substring matching.

Searching for `cuff` returned only two results, even though the word appeared in other headings, including:

- Section 2.2 — Cuff Specifications.
- Section 3.2 — Cuff Inflation Sequence.

The extracted text was inspected at the Unicode code-point level using Python. This revealed that certain letter combinations were represented by Unicode ligature characters, including:

- `\ufb00` — `ﬀ`
- `\ufb01` — `ﬁ`
- `\ufb02` — `ﬂ`

As a result, a word that visually appeared to contain ordinary letters could have a different underlying representation.

An initial attempt to replace a two-character mojibake string did not work because the stored content contained a single ligature character, not the two-character sequence displayed by the terminal.

The solution was a normalization function called `_normalize_for_search`, which expands the ligature characters into ordinary letter sequences before performing lowercase matching.

After the correction, the same search correctly returned all 12 matching nodes across both versions.

**Important limitation:** This normalization was implemented for search. It was not yet applied consistently to the content-hashing layer used for version comparisons and staleness detection.

### Phase 9 — Final validation and documentation

The final validation stage included:

- Running the pytest suite.
- Testing API behavior against real Gemini output.
- Cleaning up `requirements.txt`.
- Updating `.gitignore`.
- Making incremental Git commits and pushing them.
- Writing the README and this approach document based on the implementation and tests.

The recorded final test result was **46 passing tests out of 46**.

This result represents the reported test run during development; it does not independently prove that every possible input or production scenario is covered.

---

## 4. Data Model and Storage Design

### 4.1 Relational data model

The main document structure is:

```text
Document
└── DocumentVersion
    └── Node
        ├── heading
        ├── level
        ├── body_text
        ├── content_hash
        ├── status
        ├── matched_node_id
        ├── parent_id
        └── children
```

Each `Node` belongs to a document version and can reference its parent node. The parent-child relationship forms the document tree.

The version-matching metadata includes:

- `content_hash`: a fingerprint of the node's relevant content.
- `status`: the node's classification in the version comparison.
- `matched_node_id`: the corresponding node in another version, when a match is found.

The `Selection` entity stores a named selection, while `SelectionNode` associates the selection with specific nodes and versions.

### 4.2 Why selections are version-pinned

The system creates new node rows for the new version rather than mutating the existing Version 1 rows.

Therefore, a Version 1 selection continues to refer to the original Version 1 content after Version 2 is ingested.

This is important because test cases generated against Version 1 must be traceable to the source requirements used at generation time.

### 4.3 JSON test-case storage

Generated test cases are stored in:

```text
data/test_cases_store.json
```

The store is keyed by selection ID. Each record contains:

```json
{
  "<selection_id>": {
    "generated_at": "...",
    "source_node_hashes": {
      "<node_id>": "<content_hash>"
    },
    "test_cases": []
  }
}
```

The example above illustrates the structure; actual timestamps, node IDs, hashes, and test-case objects come from runtime data.

### 4.4 Why JSON instead of a MongoDB server?

The assignment permits a well-justified JSON-based NoSQL store.

For this small, single-document, two-version project, a JSON file avoids the operational overhead of configuring a MongoDB server, connection credentials, and a running database service.

The current workload mainly requires looking up generated results by selection ID. It does not require the scale, indexing, or concurrent-write handling that would justify an additional database service.

This is a scope-specific design decision, not a claim that JSON files are appropriate for every production workload.

---

## 5. PDF Parsing Decisions for Real Irregularities

| Observed irregularity | Implementation decision | Reason |
|---|---|---|
| General Specifications table in Section 2.1 | Preserve as a table block. | Avoid losing relationships between specification names and values. |
| Error Codes table changes between versions | Use the same generic table handling. | New rows and changed values should be detected through normal content comparison. |
| Numbered list in Section 3.3 | Preserve list items and their order. | Classification thresholds and categories are meaningful QA inputs. |
| Section 3.4 appears before 3.3 in Version 1 | Build logical hierarchy from section numbering and heading information. | Physical print order should not dictate logical section order. |
| Section 4 moves to another page in Version 2 | Treat page and block positions as metadata. | Layout changes are not necessarily content changes. |
| Version 2 has a nearly empty continuation page | Attach the content to its existing section. | Page breaks alone do not establish new section boundaries. |
| Unicode ligatures occur in extracted text | Normalize ligatures in the search layer. | Make ordinary queries match visually equivalent text. |
| Mojibake appears in the title | Document the artifact as a known limitation. | It was not prioritized during the available implementation time. |

### 5.1 Known title-text limitation

The title contains a mojibake artifact in:

`Pressure Monitor â Technical & User Manual`

This was left unresolved. It was observed during manual review, but the implementation did not establish that the issue affected the body text sent to Gemini. Correcting the underlying text-encoding issue remains a future improvement.

---

## 6. Version-Matching Strategy

### 6.1 Matching key

The system matches a later-version node to an earlier-version node using:

**(section number, normalized heading text)**

For example, the matching key for Section 3.2 is based on the section number `3.2` and its heading, `Cuff Inflation Sequence`.

Page number and physical block position are not part of the matching key.

### 6.2 Matching algorithm

```text
For each node in the new version:

    Find an earlier-version node with the same
    section number and normalized heading.

    If a match exists:
        Compare content hashes.

        If hashes match:
            status = unchanged
        Otherwise:
            status = changed
            calculate a content diff

    If no match exists:
        status = new

Any earlier-version node without a corresponding
new-version match is treated as removed.
```

The initial version is treated as the baseline, rather than being compared against an earlier version that does not exist.

### 6.3 Why use section number and heading?

The section number identifies a logical position in the manual, while the heading provides additional protection against matching two unrelated topics that happen to reuse the same number.

The content hash then distinguishes a matching section whose content has changed from one whose content is unchanged.

This strategy can detect edits to values such as battery-life specifications and cuff-related increments, provided the nodes are matched and their content hashes accurately represent the relevant text.

### 6.4 Known matching limitation

The strategy can fail when a section is both renumbered and renamed in the same version change.

For example:

```text
Version 1: 3.2 — Cuff Inflation Sequence
Version 2: 3.5 — Cuff Pressurization Steps
```

Neither part of the matching key remains the same. The current matcher may therefore classify the old node as removed and the new node as new rather than identifying a single changed section.

This behavior was not observed in the reviewed CT-200 Version 1-to-Version 2 comparison, but it is a real limitation of the matching strategy.

A more robust implementation could use body-text similarity as a secondary matching signal when the primary key fails.

---

## 7. LLM Prompting, Validation, and Error Handling

### 7.1 Input construction

The system reconstructs the selected document content from its nodes, including the headings and body text, in tree order.

That content is supplied to Gemini as the basis for test-case generation.

The purpose is to keep the generated QA ideas tied to the selected requirements instead of requesting generic test cases unrelated to the manual.

### 7.2 Structured output

The prompt requests three to five QA test-case ideas in JSON format.

The response is validated for:

- Valid JSON syntax.
- A list containing between three and five test cases.
- The expected fields for each test case.

If validation fails, the system retries once. If the output remains invalid, it returns an error rather than pretending that generation succeeded.

The implementation also handles API errors, including model availability problems, transient unavailability, and missing API credentials.

### 7.3 Error-handling principle

The endpoint should not:

- Fabricate placeholder test cases.
- Return an empty success response when generation fails.
- Hide the underlying cause of a failed generation request.

Instead, failures are surfaced as clear API errors. The implementation uses HTTP `502` for the documented upstream Gemini failures, including missing or empty API-key configuration.

The actual response detail should be checked against the current code when updating the API documentation.

### 7.4 Duplicate-generation policy

Calling the generation endpoint again for the same selection overwrites the existing stored result for that selection ID.

There is no historical record of previous generations for the same selection.

This keeps the implementation simple but prevents users from comparing older generated test cases with a later regeneration. A user who needs separate records must create another named selection.

---

## 8. Staleness Detection

### 8.1 Why staleness matters

A QA test case can become outdated when the product requirements change.

For example, a test case created from a battery-life requirement may no longer represent the latest manual after the specified battery cycle count changes.

The system records the content hashes of the source nodes when test cases are generated. These hashes provide a reference point for later comparison.

### 8.2 Generation-time process

When the test cases are generated, the JSON store records:

- The selection ID.
- The generation timestamp.
- The source-node hashes.
- The generated test cases.

This preserves a snapshot of the source content used during generation.

### 8.3 Retrieval-time process

When the staleness endpoint is called, the system:

1. Retrieves the stored test cases and their original source hashes.
2. Resolves the relevant source nodes against the latest version where a corresponding node exists.
3. Recomputes the current content hashes.
4. Compares the current hashes with the stored hashes.
5. Reports changed source nodes and their staleness status.

This can be called even before test cases have been generated, according to the documented implementation behavior.

### 8.4 Per-node staleness

Staleness is reported at the source-node level rather than only as a blanket status for the whole selection.

This is useful because a selection can contain multiple nodes, and only some of them may have changed.

### 8.5 What staleness detection cannot tell us

A hash mismatch indicates that content has changed. It does not indicate whether the change is important to the existing test cases.

A minor typo correction and a meaningful specification change can both result in a different hash.

Therefore, the current implementation identifies potential staleness but does not judge its severity or determine automatically whether the existing test cases must be regenerated.

**Important limitation:** Hash-based staleness detection is only as reliable as the content normalization, node matching, and hash-generation logic. Unicode ligature normalization is currently not applied consistently across the search and hashing layers.

---

## 9. Real Version Comparison and Output Interpretation

The recorded example comparison report contains the following counts:

| Change category | Example count |
|---|---:|
| New in Version 2 | 1 |
| Changed | 4 |
| Unchanged | 24 |
| Removed | 0 |

These are the example report values recorded during development, not values inferred from the architecture. They should be rechecked against the current database and comparison output if the underlying parser or matching logic changes.

### 9.1 Example node-diff structure

A node comparison can return the matched nodes, their status, and a unified diff showing the text changes.

Illustrative structure:

```json
{
  "section_number": "4.2",
  "status": "changed",
  "diff": "--- v1\n+++ v2\n@@\n-2 seconds\n+1.5 seconds"
}
```

This example demonstrates the kind of change being represented. It is not a substitute for the exact response schema produced by the current API.

The real Error Codes table comparison includes the E3 timing change and the addition of E6 in Version 2.

### 9.2 Why the diff is useful

A status such as `changed` establishes that the content differs, but it does not immediately explain what changed.

A unified diff makes the modification easier to review, especially when the difference affects a numerical specification or a safety-related requirement.

---

## 10. Testing and Validation Strategy

The test suite validates the components individually and the complete workflow where supported.

### 10.1 Unit testing

Unit tests cover:

- PDF extraction behavior.
- Tree hierarchy and parent-child relationships.
- Content-hash generation.
- Table extraction.
- List extraction.
- Version matching and change classification.

These tests help detect regressions when parsing or matching logic changes.

### 10.2 API testing

The Browse and Selection endpoints were manually tested using real HTTP requests before LLM integration.

PowerShell's `Invoke-RestMethod` was used to send requests. Nested response bodies were inspected with `ConvertTo-Json -Depth 10` when the default console formatting obscured their structure.

### 10.3 LLM testing

Generation was tested against actual Gemini responses, including failure scenarios such as:

- An unavailable model.
- A transient service-unavailability response.
- Missing or empty API-key configuration.
- Invalid or incomplete structured output handling.

The purpose is to verify that upstream failures are exposed clearly and that malformed output does not silently become a successful result.

### 10.4 Regression testing

After the implementation was completed, the recorded pytest run reported 46 passing tests.

The tests should be rerun after changes to:

- The PDF parser.
- Heading detection.
- Tree reconstruction.
- Content normalization.
- Hash generation.
- Version matching.
- Database models.
- API schemas.
- LLM output validation.

A passing suite provides evidence for covered behavior, but it does not eliminate the need to inspect real extraction output or validate new edge cases.

---

## 11. Development Problems and Resolutions

| Problem | Root cause | Resolution |
|---|---|---|
| `PermissionError: [WinError 32]` during database rebuild | Another process held the SQLite database file open. | Close the process or database viewer and rerun ingestion. |
| Selection API returned HTTP 500 after schema changes | Existing SQLite tables reflected the previous schema. | Rebuild the database using the updated models and ingestion script. |
| API requests failed with connection errors | Uvicorn occupied the same foreground terminal used for testing. | Run the server and API requests in separate terminals. |
| Nested JSON appeared incomplete | PowerShell formatting flattened nested structures. | Inspect the response using `ConvertTo-Json -Depth 10`. |
| Gemini returned HTTP 404 | The configured model was unavailable for the request. | Update the model configuration and surface upstream failures clearly. |
| Gemini returned HTTP 503 | Temporary upstream service unavailability. | Retry the request and report failure if it cannot succeed. |
| Searching for `cuff` missed valid nodes | Unicode ligatures made extracted text differ from ordinary ASCII spelling. | Normalize ligatures before search matching. |
| Two nodes with identical headings were not distinguished adequately in an early hash implementation | Hash identity did not sufficiently account for section context. | Review the hash-generation logic and add targeted tests. |

These incidents demonstrate why testing actual data and inspecting real responses are important. Some apparent bugs originated in the development environment or output formatting rather than the core application logic.

---

## 12. Known Limitations and Future Improvements

The following improvements were identified but are not represented as completed features.

### 12.1 Normalize content before hashing

Apply the same Unicode ligature normalization used by search to `generate_content_hash`.

Add tests for two texts that differ only in their ligature representation, and verify that the chosen normalization policy produces the intended hash result.

This would reduce false version changes and incorrect staleness signals caused by text representation rather than meaningful content differences.

### 12.2 Improve version matching

Add a fallback based on body-text similarity when both the section number and heading change.

This would help distinguish a genuinely new section from a previously existing section that was renumbered and renamed.

### 12.3 Validate selection version consistency

Reject or explicitly handle selections containing node IDs from different document versions.

Without this validation, the current implementation can create a selection that combines Version 1 and Version 2 nodes. Generation may then send a mixture of requirements to Gemini without warning.

### 12.4 Support incremental ingestion

Update `ingest_versions.py` to add a new document version without rebuilding the entire database.

The current full-rebuild workflow is manageable for the assignment's two versions, but it would become increasingly inconvenient as more versions are introduced.

### 12.5 Preserve generation history

Store separate generation records rather than overwriting the previous test cases when the same selection is regenerated.

A generation-history model would make it possible to compare older and newer test cases and investigate why a test case changed.

### 12.6 Correct the title's mojibake

Investigate the character-encoding issue that produced `â` in the title and correct it at the extraction or decoding layer.

The fix should be verified against the original PDF rather than applying an unverified replacement to all text.

### 12.7 Additional production-oriented improvements

Potential future work includes:

- Better handling of concurrent JSON-store writes.
- More comprehensive API integration tests.
- Stronger validation of generated test-case fields.
- Explicit logging of upstream LLM failures.
- More robust extraction for unusual PDF layouts.
- Incremental database migrations rather than destructive rebuilds.

---

## 13. Decision Log

### Question 1: Which part could silently produce incorrect results, and how would it be detected?

The content-hashing layer is one of the riskiest components because it can return a valid hash even when the underlying text has been normalized incorrectly or inconsistently.

The search layer expands Unicode ligatures, but the hashing layer does not yet apply the same normalization. Consequently, two visually equivalent texts could produce different hashes and be classified as changed.

A targeted unit test should construct two texts that differ only in ligature representation and assert the expected result from `generate_content_hash`.

This is preferable to assuming the current behavior is correct simply because no obvious failure has appeared in the reviewed comparison.

### Question 2: Where was simplicity prioritized over correctness or completeness, and what would break first in production?

The clearest example is overwriting generated test cases when the same selection is submitted for generation again.

This avoids implementing generation-history management, but it means that previous results disappear when a selection is regenerated. A QA reviewer cannot compare the previous output with the newer output.

The full-rebuild ingestion process is another limitation. It is acceptable for the assignment's fixed set of versions, but it would be inconvenient for a workflow that regularly receives additional manual versions.

### Question 3: What input is not handled, and what happens when it occurs?

A selection containing node IDs from different document versions is not validated or rejected by the current implementation.

For example, a selection could combine a Version 1 node with a Version 2 node. The system may accept the selection and reconstruct a combined content payload for the LLM without warning.

The resulting test cases could therefore be based on requirements from inconsistent versions.

The appropriate improvement is to validate version consistency when creating a selection and return a clear validation error when the selected nodes do not satisfy the chosen version policy.

---

## 14. Important Design Principles

The implementation follows several broader engineering principles.

**1. Inspect source data before automating it.**  
The actual PDFs determine the parser requirements.

**2. Preserve structure instead of flattening everything into text.**  
Tables, lists, headings, and parent-child relationships have different meanings.

**3. Validate foundational layers before building dependent features.**  
Tree correctness must precede reliable version matching.

**4. Separate document identity from physical layout.**  
Page and block positions are useful metadata, but they should not define logical section identity.

**5. Preserve source-version traceability.**  
A selection and its generated test cases should retain information about the exact source content used.

**6. Make failures visible.**  
An unavailable LLM should produce a clear error rather than fabricated output or an empty success response.

**7. Treat staleness as a signal, not a judgment of severity.**  
A changed hash indicates changed content; it does not establish whether the existing test cases are still adequate.

**8. Document known gaps explicitly.**  
Unresolved normalization, matching, and selection-validation issues should remain visible until they are fixed and tested.

---

## 15. Final Outcome

The CT-200 QA Assistant brings together PDF extraction, document-tree reconstruction, version-aware storage, document browsing, named selections, LLM-based test-case generation, and hash-based staleness detection.

Its main strength is the incremental development approach: the source PDFs were inspected first, parsing and tree construction were validated before versioning, and the Browse and Selection APIs were tested before the LLM layer was introduced.

The implementation also surfaced important limitations rather than treating the system as production-ready. Unicode normalization is inconsistent between search and hashing, matching can fail when a section is both renamed and renumbered, mixed-version selections are not validated, and repeated generation overwrites prior results.

These limitations provide a concrete roadmap for improving reliability, traceability, and maintainability.

**Overall conclusion:** The project demonstrates an end-to-end approach to converting versioned product documentation into structured QA inputs, while making the relationship between source requirements, document changes, generated test cases, and potential staleness explicit.

---

*This document describes the implementation and limitations recorded during development. For installation instructions, environment variables, endpoint usage, and example commands, refer to the project README. Before submission, verify all example response schemas and numerical counts against the current code and test output.*