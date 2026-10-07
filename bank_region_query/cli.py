"""
Command-line interface for bank region query
"""

import argparse
import sys
import json
from typing import List
from .core import BankRegionQuery, PatternType


def format_output(result, output_format: str = "text"):
    """Format query output"""
    if not result.success:
        return f"❌ {result.message}"
    
    if output_format == "json":
        return json.dumps({"success": True, "data": result.data}, ensure_ascii=False, indent=2)
    elif output_format == "text":
        if isinstance(result.data, dict):
            lines = []
            for key, value in result.data.items():
                lines.append(f"  {key}: {value}")
            return "\n".join(lines) if lines else str(result.data)
        elif isinstance(result.data, list):
            if result.data and isinstance(result.data[0], dict):
                # Format list of matches nicely
                lines = [f"  Found {len(result.data)} match(es):"]
                for i, match in enumerate(result.data, 1):
                    if "region" in match and "code" in match:
                        lines.append(f"    {i}. {match['region']} → {match['code']}")
                    elif "code" in match and "region" in match:
                        lines.append(f"    {i}. {match['code']} → {match['region']}")
                    else:
                        lines.append(f"    {i}. {match}")
                return "\n".join(lines)
            else:
                return "\n".join(f"  {item}" for item in result.data) if result.data else "  (empty)"
        else:
            return str(result.data)
    return str(result.data)


def choose_bank(query, bank_input):
    """Resolve a bank name for interactive use.

    A single match is used directly. 2..MAX_CHOICES matches are offered as a
    menu. Anything else (no match, too many matches, parenthesised qualifier)
    is reported and aborted -- the same outcome script mode gets.

    Returns the canonical bank name, or None when nothing was picked.
    """
    matches = query.match_banks(bank_input)
    if len(matches) == 1:
        return matches[0]
    if not matches or len(matches) > query.MAX_CHOICES:
        print(f"❌ {query.match_error(bank_input, matches)}")
        return None

    print(f"\n❓ '{bank_input}' matches {len(matches)} banks:")
    for i, name in enumerate(matches, 1):
        print(f"  {i}. {name}")
    try:
        answer = input(f"Pick 1-{len(matches)} (empty to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if answer.isdigit() and 1 <= int(answer) <= len(matches):
        return matches[int(answer) - 1]
    print("Nothing picked, cancelled.")
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Bank Region Code Query Tool with Pattern Matching",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Bank names are matched as strings against each bank's name and 别称, so
"工行", "icbc", "中国建设银行" and "建行" all reach 中国工商银行 / 建设银行.
A unique match is used directly; 0 matches or more than 3 fail and ask for a
re-query; 2-3 matches fail here and are offered as a menu in interactive mode:
  %(prog)s code -b "工行" -r "东营"
  %(prog)s resolve -b "icbc"
  %(prog)s list aliases

Pattern Matching Examples:
  # Substring match (auto-detected when no special chars)
  %(prog)s code -b "中国农业银行" -r "东营"
  
  # Wildcard match (using *)
  %(prog)s code -b "中国农业银行" -r "东*市"
  %(prog)s code -b "中国农业银行" -r "*州*"
  %(prog)s region -b "中国农业银行" -c "1*"
  
  # Regex match (using /pattern/)
  %(prog)s code -b "中国农业银行" -r "/^东.*市$/"
  %(prog)s code -b "中国农业银行" -r "/[\\u4e00-\\u9fa5]{2,3}/"
  %(prog)s region -b "中国农业银行" -c "/^00[0-9]$/"
  
  # Exact match (default)
  %(prog)s code -b "中国农业银行" -r "北京市"
  %(prog)s region -b "中国农业银行" -c "001"

  # Force specific pattern type with --pattern-type
  %(prog)s code -b "中国农业银行" -r "东营" --pattern-type regex
        """
    )
    
    parser.add_argument(
        "-d", "--data-file",
        help="Path to custom JSON data file (default: use bundled data)"
    )
    
    parser.add_argument(
        "-f", "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Get code command
    code_parser = subparsers.add_parser("code", help="Get region code by bank and region")
    code_parser.add_argument("-b", "--bank", required=True, help="Bank name")
    code_parser.add_argument("-r", "--region", required=True, help="Region pattern (supports substring, wildcard *, regex /pattern/)")
    code_parser.add_argument("-t", "--pattern-type", choices=["exact", "substring", "wildcard", "regex"], 
                            help="Pattern type (auto-detected if not specified)")
    
    # Get region command
    region_parser = subparsers.add_parser("region", help="Get region name by bank and code")
    region_parser.add_argument("-b", "--bank", required=True, help="Bank name")
    region_parser.add_argument("-c", "--code", required=True, help="Code pattern (supports substring, wildcard *, regex /pattern/)")
    region_parser.add_argument("-t", "--pattern-type", choices=["exact", "substring", "wildcard", "regex"],
                            help="Pattern type (auto-detected if not specified)")
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search across all banks")
    search_group = search_parser.add_mutually_exclusive_group(required=True)
    search_group.add_argument("-r", "--region", help="Search by region pattern")
    search_group.add_argument("-c", "--code", help="Search by code pattern")
    search_parser.add_argument("-t", "--pattern-type", choices=["exact", "substring", "wildcard", "regex"],
                              help="Pattern type (auto-detected if not specified)")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List banks, regions, or codes")
    list_parser.add_argument(
        "type",
        choices=["banks", "regions", "codes", "aliases"],
        help="What to list"
    )
    list_parser.add_argument("-b", "--bank", help="Bank name (required for regions/codes)")
    list_parser.add_argument("-p", "--pattern", help="Optional pattern to filter results")
    list_parser.add_argument("-t", "--pattern-type", choices=["exact", "substring", "wildcard", "regex"],
                            help="Pattern type for filtering (auto-detected if not specified)")

    # Resolve command
    resolve_parser = subparsers.add_parser(
        "resolve",
        help="Resolve a bank name / 简称 / pinyin abbreviation to the canonical name"
    )
    resolve_parser.add_argument("-b", "--bank", required=True,
                                help="Bank name, 简称 (工行) or pinyin abbreviation (icbc)")
    
    # Statistics command
    subparsers.add_parser("stats", help="Show statistics")
    
    # Export command
    export_parser = subparsers.add_parser("export", help="Export data to JSON")
    export_parser.add_argument("-o", "--output", required=True, help="Output file path")
    export_parser.add_argument("-b", "--bank", help="Specific bank to export (optional)")
    
    # Interactive mode
    subparsers.add_parser("interactive", help="Interactive mode")
    
    args = parser.parse_args()
    
    try:
        # Initialize query tool
        query = BankRegionQuery(args.data_file if hasattr(args, 'data_file') else None)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error initializing: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Process commands
    if args.command == "code":
        result = query.get_region_code(args.bank, args.region, args.pattern_type if hasattr(args, 'pattern_type') else None)
        print(format_output(result, args.format))
        sys.exit(0 if result.success else 1)
    
    elif args.command == "region":
        result = query.get_region_by_code(args.bank, args.code, args.pattern_type if hasattr(args, 'pattern_type') else None)
        print(format_output(result, args.format))
        sys.exit(0 if result.success else 1)
    
    elif args.command == "search":
        if args.region:
            result = query.search_by_region(args.region, args.pattern_type if hasattr(args, 'pattern_type') else None)
        else:
            result = query.search_by_code(args.code, args.pattern_type if hasattr(args, 'pattern_type') else None)
        print(format_output(result, args.format))
        sys.exit(0 if result.success else 1)
    
    elif args.command == "list":
        if args.type == "banks":
            banks = query.list_banks()
            print(f"\n📋 Available banks ({len(banks)}):")
            for bank in banks:
                print(f"  • {bank}")
        elif args.type == "regions":
            if not args.bank:
                print("Error: --bank is required for listing regions", file=sys.stderr)
                sys.exit(1)
            result = query.list_regions(args.bank, args.pattern if hasattr(args, 'pattern') else None,
                                       args.pattern_type if hasattr(args, 'pattern_type') else None)
            if result.success:
                if args.pattern:
                    print(f"\n📍 Matching regions for {args.bank} ({len(result.data)} results):")
                else:
                    print(f"\n📍 All regions for {args.bank} ({len(result.data)}):")
                for region in result.data:
                    print(f"  • {region}")
                if result.message:
                    print(f"\n  {result.message}")
            else:
                print(format_output(result, args.format))
                sys.exit(1)
        elif args.type == "codes":
            if not args.bank:
                print("Error: --bank is required for listing codes", file=sys.stderr)
                sys.exit(1)
            result = query.list_codes(args.bank, args.pattern if hasattr(args, 'pattern') else None,
                                     args.pattern_type if hasattr(args, 'pattern_type') else None)
            if result.success:
                if args.pattern:
                    print(f"\n🔢 Matching codes for {args.bank} ({len(result.data)} results):")
                else:
                    print(f"\n🔢 All codes for {args.bank} ({len(result.data)}):")
                for code in result.data:
                    print(f"  • {code}")
                if result.message:
                    print(f"\n  {result.message}")
            else:
                print(format_output(result, args.format))
                sys.exit(1)
        elif args.type == "aliases":
            result = query.list_aliases(args.bank if hasattr(args, 'bank') else None)
            if not result.success:
                print(format_output(result, args.format))
                sys.exit(1)
            if args.bank:
                print(f"\n🏷  Aliases for {args.bank} ({len(result.data)}):")
                for alias in result.data:
                    print(f"  • {alias}")
            else:
                print("\n🏷  Known bank aliases:")
                for bank, aliases in result.data.items():
                    print(f"  • {bank}: {', '.join(aliases) if aliases else '(none)'}")

    elif args.command == "resolve":
        result = query.resolve_bank(args.bank)
        if result.success:
            print(result.data)
        else:
            print(format_output(result, args.format))
        sys.exit(0 if result.success else 1)
    
    elif args.command == "stats":
        stats = query.get_statistics()
        print("\n📊 Statistics:")
        print(f"  • Total banks: {stats['total_banks']}")
        print(f"  • Total region mappings: {stats['total_region_mappings']}")
        print(f"  • Total code mappings: {stats['total_code_mappings']}")
        print(f"\n  Banks:")
        for bank in stats['banks']:
            print(f"    - {bank}")
    
    elif args.command == "export":
        success = query.export_data(args.output, args.bank if hasattr(args, 'bank') else None)
        if success:
            print(f"✅ Data exported to {args.output}")
        else:
            print("❌ Export failed", file=sys.stderr)
            sys.exit(1)
    
    elif args.command == "interactive":
        print("\n🔍 Bank Region Query - Interactive Mode (with pattern matching)")
        print("Commands:")
        print("  code <bank> <region>              - Get region code (supports patterns)")
        print("  region <bank> <code>              - Get region name (supports patterns)")
        print("  search-region <region>            - Search by region pattern")
        print("  search-code <code>                - Search by code pattern")
        print("  list banks                        - List all banks")
        print("  list regions <bank> [pattern]     - List regions for bank (optional filter)")
        print("  list codes <bank> [pattern]       - List codes for bank (optional filter)")
        print("  list aliases [bank]               - List known bank aliases")
        print("  resolve <bank>                    - Resolve an alias to the canonical name")
        print("  stats                             - Show statistics")
        print("  help                              - Show this help")
        print("  quit/exit                         - Exit")
        print("\nBank names are matched as strings against each bank's name and 别称")
        print("(工行, icbc, 中国建设银行, 建行, ...). One match is used as-is;")
        print("2-3 matches show a menu here; 0 or 4+ matches fail and ask for a re-query.")
        print("Script mode fails on 2-3 matches too.")
        print("\nPattern examples:")
        print("  - Substring: 东营")
        print("  - Wildcard: 东*市, 1*")
        print("  - Regex: /^东.*市$/, /^00[0-9]$/")
        print()
        
        while True:
            try:
                cmd = input("> ").strip()
                if not cmd:
                    continue
                
                if cmd == "quit" or cmd == "exit":
                    print("Goodbye!")
                    break
                elif cmd == "help":
                    print("\nAvailable commands:")
                    print("  code <bank> <region>              - Get region code")
                    print("  region <bank> <code>              - Get region name")
                    print("  search-region <region>            - Search by region across all banks")
                    print("  search-code <code>                - Search by code across all banks")
                    print("  list banks                        - List all banks")
                    print("  list regions <bank> [pattern]     - List regions (optional filter)")
                    print("  list codes <bank> [pattern]       - List codes (optional filter)")
                    print("  list aliases [bank]               - List known bank aliases")
                    print("  resolve <bank>                    - Resolve an alias to the canonical name")
                    print("  stats                             - Show statistics")
                    print("  help                              - Show this help")
                    print("  quit/exit                         - Exit\n")
                elif cmd.startswith("code "):
                    parts = cmd.split(maxsplit=2)
                    if len(parts) < 3:
                        print("Usage: code <bank> <region>")
                        continue
                    _, bank, region = parts
                    bank = choose_bank(query, bank)
                    if bank is None:
                        continue
                    result = query.get_region_code(bank, region)
                    print(format_output(result))
                elif cmd.startswith("region "):
                    parts = cmd.split(maxsplit=2)
                    if len(parts) < 3:
                        print("Usage: region <bank> <code>")
                        continue
                    _, bank, code = parts
                    bank = choose_bank(query, bank)
                    if bank is None:
                        continue
                    result = query.get_region_by_code(bank, code)
                    print(format_output(result))
                elif cmd.startswith("search-region "):
                    region = cmd[14:].strip()
                    result = query.search_by_region(region)
                    print(format_output(result))
                elif cmd.startswith("search-code "):
                    code = cmd[12:].strip()
                    result = query.search_by_code(code)
                    print(format_output(result))
                elif cmd == "list banks":
                    banks = query.list_banks()
                    print(f"\nAvailable banks ({len(banks)}):")
                    for bank in banks:
                        print(f"  • {bank}")
                elif cmd.startswith("list aliases"):
                    parts = cmd.split(maxsplit=2)
                    bank = parts[2].strip() if len(parts) > 2 else None
                    if bank in ("-b", "--bank"):
                        bank = None
                    elif bank and bank.split(maxsplit=1)[0] in ("-b", "--bank"):
                        bank = bank.split(maxsplit=1)[1] if len(bank.split(maxsplit=1)) > 1 else None
                    if bank is not None:
                        bank = choose_bank(query, bank)
                        if bank is None:
                            continue
                    result = query.list_aliases(bank)
                    if not result.success:
                        print(format_output(result))
                    elif bank:
                        print(f"\nAliases for {bank} ({len(result.data)}):")
                        for alias in result.data:
                            print(f"  • {alias}")
                    else:
                        print("\nKnown bank aliases:")
                        for name, aliases in result.data.items():
                            print(f"  • {name}: {', '.join(aliases) if aliases else '(none)'}")
                elif cmd.startswith("resolve "):
                    bank = choose_bank(query, cmd[len("resolve "):].strip())
                    if bank is not None:
                        print(bank)
                elif cmd.startswith("list regions "):
                    rest = cmd[len("list regions "):].strip().split(maxsplit=1)
                    if not rest:
                        print("Usage: list regions <bank> [pattern]")
                        continue
                    bank = choose_bank(query, rest[0])
                    if bank is None:
                        continue
                    pattern = rest[1] if len(rest) > 1 else None
                    result = query.list_regions(bank, pattern)
                    if result.success:
                        if pattern:
                            print(f"\nMatching regions ({len(result.data)}):")
                        else:
                            print(f"\nAll regions ({len(result.data)}):")
                        for region in result.data:
                            print(f"  • {region}")
                    else:
                        print(format_output(result))
                elif cmd.startswith("list codes "):
                    rest = cmd[len("list codes "):].strip().split(maxsplit=1)
                    if not rest:
                        print("Usage: list codes <bank> [pattern]")
                        continue
                    bank = choose_bank(query, rest[0])
                    if bank is None:
                        continue
                    pattern = rest[1] if len(rest) > 1 else None
                    result = query.list_codes(bank, pattern)
                    if result.success:
                        if pattern:
                            print(f"\nMatching codes ({len(result.data)}):")
                        else:
                            print(f"\nAll codes ({len(result.data)}):")
                        for code in result.data:
                            print(f"  • {code}")
                    else:
                        print(format_output(result))
                elif cmd == "stats":
                    stats = query.get_statistics()
                    print(f"\nTotal banks: {stats['total_banks']}")
                    print(f"Total region mappings: {stats['total_region_mappings']}")
                    print(f"Total code mappings: {stats['total_code_mappings']}")
                else:
                    print("Unknown command. Type 'help' for available commands.")
            
            except KeyboardInterrupt:
                print("\nGoodbye!")
                break
            except EOFError:
                # stdin closed (e.g. piped input ran out) -- without this the
                # loop would spin forever printing the same error
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"Error: {e}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
