# NFRA Daily NotebookLM Sync Design

## Goal

Build a reliable daily workflow that checks the National Financial Regulatory Administration (NFRA) English "Rules and Regulations" listing for rules published on the current day, converts each matching rule's web content into a local PDF, and uploads the PDF to the existing NotebookLM notebook named `NFRA`.

The first end-to-end verification will intentionally process the latest available rule dated 2026-07-07. Production runs will only process rules whose NFRA publication date matches the current date in the Asia/Shanghai timezone.

## Source

- Listing page: `https://www.nfra.gov.cn/en/view/pages/ItemList.html?itemPId=973&itemId=981&itemUrl=ItemListRightList.html&itemTitle=Rules%20and%20Regulations&itemPTitle=Rules%20and%20Regulations`
- Listing data: NFRA's public JSON endpoint for item ID `981`
- Detail page: `https://www.nfra.gov.cn/en/view/pages/ItemDetail.html?docId=<doc_id>&itemId=981`

The workflow will use the JSON endpoint for deterministic listing and date filtering, then retrieve the English detail page for the document content.

## Architecture

The implementation will be split into focused components:

1. **NFRA client**
   - Fetches the current first page of item `981` from the public JSON endpoint.
   - Normalizes each item into a document ID, title, publication timestamp, and detail URL.
   - Fetches and extracts the meaningful English detail-page content.

2. **Date selector**
   - Uses `Asia/Shanghai` as the authoritative timezone.
   - In normal mode, selects only documents whose NFRA publication date is today.
   - Accepts an explicit target date for controlled backfills and end-to-end verification.

3. **PDF writer**
   - Produces a clean PDF containing the title, publication date, source URL, NFRA document ID, and extracted web content.
   - Writes final files under `output/pdf/`.
   - Uses the filename format `yyyymmdd-<first 10 title characters>.pdf` after removing Windows-invalid filename characters and trimming trailing spaces or periods.
   - If two documents on the same date produce the same truncated filename, appends `-<doc_id>` to avoid overwriting.

4. **NotebookLM uploader**
   - Resolves the existing notebook whose title exactly matches `NFRA`.
   - Uploads each generated PDF with `notebooklm source add` and waits for source processing.
   - Does not create a replacement notebook when `NFRA` cannot be resolved.

5. **State and reporting**
   - Stores per-document progress in a dedicated repository runtime state file.
   - Records the NFRA document ID, publication date, PDF path, NotebookLM notebook ID, source ID, and successful synchronization timestamp.
   - Treats a document as fully synchronized only after NotebookLM upload succeeds.
   - Emits a machine-readable summary of matched, generated, uploaded, skipped, and failed documents.

6. **Windows scheduling wrapper**
   - Provides a PowerShell entry point suitable for both manual runs and Windows Task Scheduler.
   - Registers a daily task for 20:00 Asia/Shanghai local time only after the manual end-to-end verification is accepted.

## Data Flow

1. Determine the target date, defaulting to the current Asia/Shanghai date.
2. Fetch the NFRA listing JSON for item `981`.
3. Select every row whose publication date equals the target date.
4. Skip rows already marked as successfully uploaded unless an explicit force option is used.
5. Fetch and extract each selected rule's English detail page.
6. Generate the local PDF using the stable naming convention.
7. Resolve the NotebookLM notebook `NFRA` and upload the PDF.
8. Wait for NotebookLM source processing, then persist successful state.
9. Return a summary. A day with no matching publications is a successful no-op.

## Idempotency and Recovery

- NFRA document ID is the primary identity, independent of title changes or filename collisions.
- Re-running after a completed upload skips that document.
- A generated PDF may remain on disk after an upload failure, but the document remains eligible for upload retry.
- State writes will be atomic so interruption cannot leave a partially written state file.
- A force option may regenerate and re-upload a document for troubleshooting, but it is never enabled in the scheduled run.

## Error Handling

- Network timeouts and non-success HTTP responses identify the URL and processing stage.
- An invalid listing response, missing document ID, empty extracted body, PDF generation failure, missing `NFRA` notebook, CLI authentication failure, upload failure, or source-processing failure produces a clear failed entry.
- Multiple matching documents are processed independently. One failure does not prevent other documents from being attempted.
- The overall process exits nonzero if any selected document fails, allowing Task Scheduler history or monitoring to identify the failed run.
- No document is marked synchronized until its NotebookLM source has been accepted successfully.

## PDF Content and Quality

The PDF uses a restrained document layout with:

- Full title as the main heading
- NFRA publication date
- Clickable source URL
- NFRA document ID
- Cleaned body content with preserved paragraph order and readable list structure
- Page numbers and consistent margins

Verification will include text extraction to confirm expected title, metadata, and representative body text, followed by page rendering and visual inspection for clipping, overlap, broken glyphs, malformed links, and poor pagination.

## Testing Strategy

Development will use test-first implementation. Automated tests will cover:

- Selection of documents on the target Asia/Shanghai date
- Successful no-op when no documents match
- Explicit backfill date selection
- First-10-character title truncation
- Windows-invalid filename removal and trailing-character cleanup
- Filename collision suffixing with the NFRA document ID
- Detail-page body extraction and rejection of empty content
- State-based idempotent skipping
- Retry eligibility after PDF generation succeeds but upload fails
- Exact NotebookLM notebook resolution
- Correct `notebooklm source add` and source-wait command construction
- Partial failure summary and nonzero exit behavior

HTTP behavior will be tested with captured minimal response fixtures. NotebookLM subprocess execution will be isolated behind a command boundary so command construction and result handling can be tested deterministically without creating remote sources during unit tests.

## Verification Run

The initial end-to-end run will use target date `2026-07-07`, because the NFRA listing has no publication dated 2026-08-04 and its newest listed rule is dated 2026-07-07.

Acceptance criteria for the run:

1. The expected 2026-07-07 rule is selected from the live NFRA endpoint.
2. A readable PDF is created in `output/pdf/` using the agreed filename rule.
3. PDF text and rendered pages pass content and layout checks.
4. The PDF is uploaded to the existing NotebookLM notebook `NFRA`.
5. NotebookLM reports successful source processing.
6. A second non-force run skips the same document without uploading a duplicate.

## Daily Operation

After the verification run is accepted, a Windows scheduled task will execute the PowerShell wrapper every day at 20:00 local time. The scheduled command will use normal current-day mode, the persistent state file, and no force option. If the NFRA publishes no rules that day, the task will complete successfully without creating a PDF or calling NotebookLM upload.

## Out of Scope

- Monitoring other NFRA listing categories
- Translating English pages into Chinese
- Downloading the NFRA-provided Chinese source PDF instead of converting the English web content
- Creating NotebookLM artifacts such as audio, reports, or slide decks
- Email, chat, or other external notifications for failed scheduled runs
