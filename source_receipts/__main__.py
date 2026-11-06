import argparse
import json
from pathlib import Path
from .core import ProcessingConfig, compare, create_receipt, from_crawl_result


def main():
    parser = argparse.ArgumentParser(description="Offline RAG source provenance and change detection")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("file", type=Path)
    create.add_argument("--url", required=True)
    create.add_argument("--pipeline-version", default="1")
    create.add_argument("--fetched-at")
    create.add_argument("--output", type=Path)
    diff = sub.add_parser("compare")
    diff.add_argument("previous", type=Path)
    diff.add_argument("current", type=Path)
    diff.add_argument("--output", type=Path)
    crawl = sub.add_parser("crawl-result")
    crawl.add_argument("file", type=Path)
    crawl.add_argument("--variant", choices=["raw_markdown", "fit_markdown"], default="raw_markdown")
    crawl.add_argument("--output", type=Path)
    demo = sub.add_parser("demo")
    demo.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "create":
            report = create_receipt(args.file.read_text(), args.url,
                config=ProcessingConfig(pipeline_version=args.pipeline_version), fetched_at=args.fetched_at)
        elif args.command == "compare":
            report = compare(json.loads(args.previous.read_text()), json.loads(args.current.read_text()))
        elif args.command == "crawl-result":
            report = from_crawl_result(json.loads(args.file.read_text()),
                config=ProcessingConfig(extractor="crawl4ai", markdown_variant=args.variant))
        else:
            stamp = "2026-11-05T18:00:00Z"
            a = create_receipt("# Example\nOpening time: 19:00", "https://example.org/events", observed_at=stamp)
            b = create_receipt("# Example\nOpening time: 20:00", "https://example.org/events", observed_at=stamp)
            c = create_receipt("# Example\nOpening time: 19:00", "https://example.org/events", observed_at=stamp, config=ProcessingConfig(pipeline_version="2"))
            report = dict(original=a, identical=compare(a, a), changed_content=compare(a, b), changed_pipeline=compare(a, c),
                limitations="Receipts contain hashes, not signatures. Unknown fetch times remain null.")
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.error(str(exc))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
