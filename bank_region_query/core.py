"""
Core query functionality for bank region codes
"""

import json
import re
import unicodedata
from typing import Dict, List, Optional, Union, Tuple, Any
from pathlib import Path
from dataclasses import dataclass


@dataclass
class QueryResult:
    """Represents a query result"""
    success: bool
    data: Union[str, List[str], Dict, None]
    message: str = ""
    
    def __str__(self):
        if self.success:
            if isinstance(self.data, (list, dict)):
                import json
                return json.dumps(self.data, ensure_ascii=False, indent=2)
            return str(self.data)
        return f"Error: {self.message}"


class PatternType:
    """Pattern matching types"""
    EXACT = "exact"
    SUBSTRING = "substring"
    WILDCARD = "wildcard"
    REGEX = "regex"


class BankRegionQuery:
    """
    Query bank region codes and regions
    
    Supports:
    - Query region code by bank name and region name
    - Query region name by bank name and region code
    - Pattern matching: exact, substring, wildcard (*), regex
    - List all banks, regions, codes
    - Bank name matching: canonical name, 简称, pinyin abbreviation

    Pattern Rules:
    - Default: substring match (e.g., "东营" matches any region containing "东营")
    - =prefix: exact match (e.g., "=北京市" matches exactly "北京市")
    - Contains *: wildcard match (e.g., "东*市" matches "东莞市", "东营市")
    - Starts with ^ or ends with $: regex match (e.g., "^东.*市$")
    - /pattern/: explicit regex match (e.g., "/^东.*市$/")

    Bank Name Matching:
    Any method taking a bank name matches it as a string against each bank's
    canonical name and 别称 (data/bank_aliases.json, from ~/Documents/balance.xlsx
    sheet 银行缩写), ignoring whitespace, full-width/half-width and letter case.
    A 别称 matches exactly; CJK names also match by containment, so "工商银行",
    "工行", "icbc" and "中国建设银行" all work. A query matching exactly one bank
    is used as-is; one matching 0 or more than MAX_CHOICES banks fails and asks
    for a re-query; one matching 2..3 banks fails in script mode and is offered
    as a menu in interactive mode.
    """
    
    def __init__(self, data_file: Optional[str] = None):
        """
        Initialize the query tool
        
        Args:
            data_file: Path to JSON data file. If None, uses bundled data
        """
        if data_file is None:
            # Use bundled data
            data_path = Path(__file__).parent / "data" / "bank_region_codes.json"
        else:
            data_path = Path(data_file)
        
        if not data_path.exists():
            raise FileNotFoundError(f"Data file not found: {data_path}")

        # Alias table: prefer one shipped next to the data file in use, fall
        # back to the bundled one (bundled data file -> same directory).
        self._alias_paths = [
            data_path.parent / self.ALIAS_FILE,
            Path(__file__).parent / "data" / self.ALIAS_FILE,
        ]

        with open(data_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

        self._build_index()

    def _build_index(self):
        """Build additional indexes for faster searching"""
        self.bank_list = list(self.data.keys())
        self.region_index = {}
        self.code_index = {}
        
        for bank_name, bank_data in self.data.items():
            # Index regions
            for region in bank_data.get("region_to_code", {}).keys():
                if region not in self.region_index:
                    self.region_index[region] = []
                self.region_index[region].append(bank_name)
            
            # Index codes
            for code in bank_data.get("code_to_region", {}).keys():
                if code not in self.code_index:
                    self.code_index[code] = []
                self.code_index[code].append(bank_name)

        self._build_bank_match_strings()

    # ─── Bank name matching (string containment over names + 别称) ──────────
    #
    # Policy:
    #   exactly 1 candidate   -> used
    #   0 or > MAX_CHOICES    -> fail, ask the caller to re-query
    #   2 .. MAX_CHOICES      -> ambiguous: the API fails and lists the
    #                            candidates so an interactive caller can pick
    #                            one, script callers must re-query

    ALIAS_FILE = "bank_aliases.json"
    MAX_CHOICES = 3

    # CJK Unified Ideographs (+ Extension A); every bank name is written in it.
    CJK_RE = re.compile(r'[㐀-鿿]')

    @classmethod
    def _may_contain(cls, a: str, b: str) -> bool:
        """Whether a containment match between two strings may be trusted.

        Only between CJK strings. Applying it to pinyin abbreviations would
        collide on shared prefixes -- cmb ⊂ cmbc and boc ⊂ bocom, so 招商银行's
        "cmb" would also match 中国民生银行, and 中国银行's "boc" would also
        match 交通银行. Abbreviations must therefore match exactly, which is
        safe because they are opaque identifiers rather than readable names."""
        return bool(cls.CJK_RE.search(a)) and bool(cls.CJK_RE.search(b))

    @staticmethod
    def _normalize_bank_name(name) -> str:
        """Fold full-width to half-width (NFKC), remove all whitespace, and
        casefold, so ' ICBC　' and 'icbc' behave identically."""
        text = unicodedata.normalize("NFKC", str(name))
        return re.sub(r"\s+", "", text).casefold()

    def _load_aliases(self) -> Dict[str, List[str]]:
        """Read the 别称 table (canonical key -> [alias, ...]) taken from the
        workbook's 银行缩写 sheet.

        A missing or unreadable file is not fatal: matching then runs over the
        canonical bank names alone."""
        payload = None
        for path in getattr(self, "_alias_paths", []):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                break
            except (OSError, ValueError):
                continue
        if not isinstance(payload, dict):
            return {}
        aliases = payload.get("aliases") or {}
        # Ignore entries for banks this data file does not know about
        return {k: v for k, v in aliases.items() if k in self.data}

    def _build_bank_match_strings(self):
        """Per bank, every string a query may be matched against, normalized:
        the canonical name plus its 别称.

        The strings are taken verbatim from the data file and the workbook --
        nothing is derived or invented here, so a match can always be traced
        back to a name that actually exists somewhere."""
        self._bank_match_strings = {
            canonical: [self._normalize_bank_name(canonical)]
            for canonical in self.bank_list
        }
        for canonical, aliases in self._load_aliases().items():
            bucket = self._bank_match_strings[canonical]
            for alias in aliases:
                normalized = self._normalize_bank_name(alias)
                if normalized and normalized not in bucket:
                    bucket.append(normalized)

    def match_banks(self, bank_name: str) -> List[str]:
        """Banks whose name or 别称 matches the input, in data-file order.

        A 别称 matches exactly (after normalization). Bank names additionally
        match by containment, both ways: the input may be part of a name
        ("农业银行" in "中国农业银行") or contain one ("中国农业银行北京分行").
        Containment is only applied between CJK strings -- see _may_contain().
        Returns an empty list for input carrying a parenthesised qualifier --
        see match_error().

        Examples:
            >>> query.match_banks("工行")
            ['中国工商银行']
            >>> query.match_banks("cmb")
            ['招商银行']
            >>> query.match_banks("商银行")
            ['中国工商银行', '招商银行', '浙商银行']
            >>> query.match_banks("银行")
            [... 15 banks ...]
        """
        normalized = self._normalize_bank_name(bank_name)
        if not normalized:
            return []

        # Refused rather than matched: 中国工商银行（亚洲）and 中国建设银行
        # （亚洲）are separate entities, not spellings of 中国工商银行 /
        # 建设银行, so a qualifier must not be stripped and ignored.
        if re.search(r"[()]", normalized):
            return []

        matches = []
        for canonical in self.bank_list:
            for s in self._bank_match_strings[canonical]:
                if normalized == s or (
                    self._may_contain(normalized, s)
                    and (normalized in s or s in normalized)
                ):
                    matches.append(canonical)
                    break
        return matches

    def resolve_bank_name(self, bank_name: str) -> Optional[str]:
        """The single bank the input matches, or None when the match is not
        unique (0 candidates, 2..MAX_CHOICES, or more than MAX_CHOICES).

        Accepts the canonical name, a 简称 ("工行"), a pinyin abbreviation
        ("icbc") and variants differing only by whitespace, full-width
        characters or letter case.

        Examples:
            >>> query.resolve_bank_name("icbc")
            '中国工商银行'
            >>> query.resolve_bank_name("中国建设银行")
            '建设银行'
            >>> query.resolve_bank_name("商银行") is None   # 2 candidates
            True
            >>> query.resolve_bank_name("银行") is None     # 15 candidates
            True
        """
        matches = self.match_banks(bank_name)
        return matches[0] if len(matches) == 1 else None

    def match_error(self, bank_name: str, matches: Optional[List[str]] = None) -> str:
        """Why the input did not resolve, phrased as a re-query instruction."""
        if matches is None:
            matches = self.match_banks(bank_name)

        if not matches and re.search(r"[()]", self._normalize_bank_name(bank_name)):
            return (f"Bank '{bank_name}' carries a parenthesised qualifier, which "
                    f"may denote a different entity (中国建设银行（亚洲）is not "
                    f"建设银行). Please re-query with the exact bank name. "
                    f"Known banks: {', '.join(self.bank_list)}")

        if not matches:
            return (f"Bank '{bank_name}' matched no bank. "
                    f"Please re-query. Known banks: {', '.join(self.bank_list)}")

        if len(matches) > self.MAX_CHOICES:
            return (f"Bank '{bank_name}' matched {len(matches)} banks, more than "
                    f"the {self.MAX_CHOICES} allowed. Please re-query with a more "
                    f"specific name. Candidates: {', '.join(matches)}")

        listing = ', '.join(f"{i}. {m}" for i, m in enumerate(matches, 1))
        return (f"Bank '{bank_name}' matched {len(matches)} banks. "
                f"Please re-query with one of them: {listing}")

    def _coerce_bank_name(self, bank_name: str) -> Tuple[Optional[str], str, str]:
        """Resolve a bank name for a query method.

        Returns (canonical name | None, resolution note, error message)."""
        matches = self.match_banks(bank_name)
        if len(matches) != 1:
            return None, "", self.match_error(bank_name, matches)
        canonical = matches[0]
        if canonical == bank_name:
            return canonical, "", ""
        return canonical, f"bank '{bank_name}' resolved to '{canonical}'", ""

    def resolve_bank(self, bank_name: str) -> QueryResult:
        """Resolve a bank name / 别称 to the canonical name used by the data.

        Args:
            bank_name: Canonical name, 简称 (工行) or pinyin abbreviation (icbc)

        Returns:
            QueryResult whose data is the canonical bank name. Fails when the
            input matches no bank, 2..MAX_CHOICES banks, or more.

        Examples:
            >>> query.resolve_bank("工行").data
            '中国工商银行'
            >>> query.resolve_bank("商银行").message
            "Bank '商银行' matched 2 banks. Please re-query with one of them: 1. 招商银行, 2. 浙商银行"
        """
        canonical, note, error = self._coerce_bank_name(bank_name)
        if canonical is None:
            return QueryResult(success=False, data=None, message=error)
        return QueryResult(success=True, data=canonical, message=note)

    def list_aliases(self, bank_name: Optional[str] = None) -> QueryResult:
        """List known 别称, for one bank or all banks."""
        table = self._load_aliases()
        if bank_name is None:
            return QueryResult(success=True, data=table)

        canonical, _, error = self._coerce_bank_name(bank_name)
        if canonical is None:
            return QueryResult(success=False, data=None, message=error)
        return QueryResult(success=True, data=table.get(canonical, []))

    def _detect_pattern_type(self, pattern: str) -> str:
        """
        Detect the pattern type from the input string
        
        Rules:
        - /pattern/ -> regex
        - =pattern -> exact match (explicit)
        - * in pattern -> wildcard
        - pattern starting with ^ or ending with $ -> regex (implicit)
        - default -> substring match
        
        Args:
            pattern: Input pattern string
            
        Returns:
            Pattern type: exact, substring, wildcard, or regex
        """
        # Check for explicit regex pattern (starts and ends with /)
        if pattern.startswith('/') and pattern.endswith('/'):
            return PatternType.REGEX
        
        # Check for explicit exact match (starts with =)
        if pattern.startswith('='):
            return PatternType.EXACT
        
        # Check for implicit regex (starts with ^ or ends with $)
        if pattern.startswith('^') or pattern.endswith('$'):
            return PatternType.REGEX
        
        # Check for wildcard pattern (contains *)
        if '*' in pattern:
            return PatternType.WILDCARD
        
        # Default to substring match
        return PatternType.SUBSTRING
    
    def _pattern_to_regex(self, pattern: str, pattern_type: str) -> re.Pattern:
        """
        Convert pattern to regex based on type
        
        Args:
            pattern: Input pattern
            pattern_type: Type of pattern
            
        Returns:
            Compiled regex pattern
        """
        if pattern_type == PatternType.REGEX:
            # Remove the delimiters /pattern/ if present
            if pattern.startswith('/') and pattern.endswith('/'):
                regex_pattern = pattern[1:-1]
            else:
                regex_pattern = pattern
            return re.compile(regex_pattern)
        
        elif pattern_type == PatternType.WILDCARD:
            # Convert wildcard * to regex .*
            # Escape other regex special characters
            escaped = re.escape(pattern)
            # Replace escaped \* with .*
            regex_pattern = escaped.replace(r'\*', '.*')
            return re.compile(f'^{regex_pattern}$')
        
        elif pattern_type == PatternType.SUBSTRING:
            # Simple substring match - check if pattern appears anywhere
            return re.compile(re.escape(pattern))
        
        elif pattern_type == PatternType.EXACT:
            # Remove leading = if present
            if pattern.startswith('='):
                pattern = pattern[1:]
            return re.compile(f'^{re.escape(pattern)}$')
        
        else:  # EXACT
            return re.compile(f'^{re.escape(pattern)}$')
    
    _CODE_CANONICAL_RE = re.compile(r'^[㐀-鿿]+(\d+)$')

    def _canonical_code(self, code: str) -> str:
        """Strip a leading Chinese-character prefix (CJK Unified Ideographs +
        Extension A) so e.g. "萧山227" canonicalizes to "227". Non-Chinese
        prefixes are left untouched."""
        m = self._CODE_CANONICAL_RE.match(code)
        return m.group(1) if m else code

    def _match_code(self, code: str, pattern: str, pattern_type: str) -> bool:
        """Match a code, also trying the digits-only canonical form so patterns
        like "227" or "=227" match stored keys like "萧山227"."""
        if self._match_pattern(code, pattern, pattern_type):
            return True
        canonical = self._canonical_code(code)
        if canonical != code and self._match_pattern(canonical, pattern, pattern_type):
            return True
        return False

    def _match_pattern(self, text: str, pattern: str, pattern_type: str = None) -> bool:
        """
        Check if text matches pattern
        
        Args:
            text: Text to match against
            pattern: Pattern to match
            pattern_type: Optional pattern type (auto-detect if None)
            
        Returns:
            True if matches, False otherwise
        """
        if pattern_type is None:
            pattern_type = self._detect_pattern_type(pattern)
        
        if pattern_type == PatternType.SUBSTRING:
            return pattern in text
        
        regex = self._pattern_to_regex(pattern, pattern_type)
        return bool(regex.search(text))
    
    def _search_regions_by_pattern(self, bank_name: str, pattern: str, pattern_type: str = None) -> List[Dict[str, str]]:
        """
        Search regions using pattern matching
        
        Args:
            bank_name: Bank name
            pattern: Pattern to match
            pattern_type: Optional pattern type
            
        Returns:
            List of matching regions with their codes
        """
        if bank_name not in self.data:
            return []
        
        if pattern_type is None:
            pattern_type = self._detect_pattern_type(pattern)
        
        region_to_code = self.data[bank_name].get("region_to_code", {})
        matches = []
        
        for region, code in region_to_code.items():
            if self._match_pattern(region, pattern, pattern_type):
                matches.append({"region": region, "code": code})
        
        return matches
    
    def _search_codes_by_pattern(self, bank_name: str, pattern: str, pattern_type: str = None) -> List[Dict[str, str]]:
        """
        Search codes using pattern matching
        
        Args:
            bank_name: Bank name
            pattern: Pattern to match
            pattern_type: Optional pattern type
            
        Returns:
            List of matching codes with their regions
        """
        if bank_name not in self.data:
            return []
        
        if pattern_type is None:
            pattern_type = self._detect_pattern_type(pattern)
        
        code_to_region = self.data[bank_name].get("code_to_region", {})
        matches = []
        
        for code, region in code_to_region.items():
            if self._match_code(code, pattern, pattern_type):
                matches.append({"code": code, "region": region})
        
        return matches
    
    def get_region_code(self, bank_name: str, region_pattern: str, pattern_type: str = None) -> QueryResult:
        """
        Get region code by bank name and region pattern
        
        Args:
            bank_name: Name of the bank (e.g., "中国农业银行")
            region_pattern: Region pattern 
                - "北京市" or "=北京市" -> exact match
                - "东营" -> substring match (matches any region containing "东营")
                - "东*市" -> wildcard match
                - "/^东.*市$/" or "^东.*市$" -> regex match
            pattern_type: Optional pattern type (auto-detect if None)
            
        Returns:
            QueryResult with region code(s)
            
        Examples:
            >>> query.get_region_code("中国农业银行", "北京市")  # Substring (matches any containing 北京)
            >>> query.get_region_code("中国农业银行", "=北京市")  # Exact match
            >>> query.get_region_code("中国农业银行", "东营")  # Substring match (like *东营*)
            >>> query.get_region_code("中国农业银行", "^东.*市$")  # Regex match
            >>> query.get_region_code("中国农业银行", "东*市")  # Wildcard match
        """
        canonical, note, error = self._coerce_bank_name(bank_name)
        if canonical is None:
            return QueryResult(
                success=False,
                data=None,
                message=error
            )

        # Auto-detect pattern type if not specified
        if pattern_type is None:
            pattern_type = self._detect_pattern_type(region_pattern)

        # Search using pattern matching
        matches = self._search_regions_by_pattern(canonical, region_pattern, pattern_type)

        if matches:
            # If there's exactly one match, return just the code for convenience
            if len(matches) == 1:
                return QueryResult(
                    success=True,
                    data=matches[0]["code"],
                    message=note
                )
            else:
                # Multiple matches - return all matches with their codes
                return QueryResult(
                    success=True,
                    data=matches,
                    message="; ".join(filter(None, [note, f"Found {len(matches)} matching region(s)"]))
                )
        return QueryResult(
            success=False,
            data=None,
            message=f"No region matching '{region_pattern}' found for bank '{canonical}'"
        )
    
    def get_region_by_code(self, bank_name: str, code_pattern: str, pattern_type: str = None) -> QueryResult:
        """
        Get region name by bank name and code pattern
        
        Args:
            bank_name: Name of the bank (e.g., "中国农业银行")
            code_pattern: Code pattern
                - "001" or "=001" -> exact match
                - "1" -> substring match (matches any code containing "1")
                - "1*" -> wildcard match
                - "/^00[0-9]$/" or "^00[0-9]$" -> regex match
            pattern_type: Optional pattern type (auto-detect if None)
            
        Returns:
            QueryResult with region name(s)
            
        Examples:
            >>> query.get_region_by_code("中国农业银行", "1")  # Substring (matches any containing 1)
            >>> query.get_region_by_code("中国农业银行", "=001")  # Exact match
            >>> query.get_region_by_code("中国农业银行", "^00[0-9]$")  # Regex match
            >>> query.get_region_by_code("中国农业银行", "1*")  # Wildcard match (starts with 1)
        """
        canonical, note, error = self._coerce_bank_name(bank_name)
        if canonical is None:
            return QueryResult(
                success=False,
                data=None,
                message=error
            )

        # Auto-detect pattern type if not specified
        if pattern_type is None:
            pattern_type = self._detect_pattern_type(code_pattern)

        # Search using pattern matching
        matches = self._search_codes_by_pattern(canonical, code_pattern, pattern_type)

        if matches:
            # If there's exactly one match, return just the region for convenience
            if len(matches) == 1:
                return QueryResult(
                    success=True,
                    data=matches[0]["region"],
                    message=note
                )
            else:
                # Multiple matches - return all matches with their codes
                return QueryResult(
                    success=True,
                    data=matches,
                    message="; ".join(filter(None, [note, f"Found {len(matches)} matching code(s)"]))
                )

        return QueryResult(
            success=False,
            data=None,
            message=f"No code matching '{code_pattern}' found for bank '{canonical}'"
        )
    
    def _fuzzy_search_region(self, bank_name: str, query: str) -> List[Dict[str, str]]:
        """Fuzzy search for regions (legacy method, kept for compatibility)"""
        if bank_name not in self.data:
            return []
        
        region_to_code = self.data[bank_name].get("region_to_code", {})
        matches = []
        
        for region, code in region_to_code.items():
            if query in region or region in query:
                matches.append({"region": region, "code": code})
        
        return matches
    
    def search_by_region(self, region_pattern: str, pattern_type: str = None) -> QueryResult:
        """
        Search all banks by region pattern
        
        Args:
            region_pattern: Region pattern to search
            pattern_type: Optional pattern type (auto-detect if None)
            
        Returns:
            QueryResult with all banks and their codes for matching regions
            
        Examples:
            >>> query.search_by_region("北京市")  # Substring match
            >>> query.search_by_region("=北京市")  # Exact match
            >>> query.search_by_region("东营")  # Substring match
            >>> query.search_by_region("^东.*市$")  # Regex match
        """
        if pattern_type is None:
            pattern_type = self._detect_pattern_type(region_pattern)
        
        results = {}
        matched_count = 0
        
        for bank_name in self.bank_list:
            matches = self._search_regions_by_pattern(bank_name, region_pattern, pattern_type)
            if matches:
                results[bank_name] = matches
                matched_count += len(matches)
        
        if results:
            return QueryResult(
                success=True,
                data=results,
                message=f"Found {matched_count} matching region(s) across {len(results)} bank(s)"
            )
        
        return QueryResult(
            success=False,
            data=None,
            message=f"No region matching '{region_pattern}' found in any bank"
        )
    
    def search_by_code(self, code_pattern: str, pattern_type: str = None) -> QueryResult:
        """
        Search all banks by code pattern
        
        Args:
            code_pattern: Code pattern to search
            pattern_type: Optional pattern type (auto-detect if None)
            
        Returns:
            QueryResult with all banks and their regions for matching codes
            
        Examples:
            >>> query.search_by_code("001")  # Substring match
            >>> query.search_by_code("=001")  # Exact match
            >>> query.search_by_code("1")  # Substring match
            >>> query.search_by_code("^00[0-9]$")  # Regex match
        """
        if pattern_type is None:
            pattern_type = self._detect_pattern_type(code_pattern)
        
        results = {}
        matched_count = 0
        
        for bank_name in self.bank_list:
            matches = self._search_codes_by_pattern(bank_name, code_pattern, pattern_type)
            if matches:
                results[bank_name] = matches
                matched_count += len(matches)
        
        if results:
            return QueryResult(
                success=True,
                data=results,
                message=f"Found {matched_count} matching code(s) across {len(results)} bank(s)"
            )
        
        return QueryResult(
            success=False,
            data=None,
            message=f"No code matching '{code_pattern}' found in any bank"
        )
    
    def list_banks(self) -> List[str]:
        """List all available banks"""
        return self.bank_list.copy()
    
    def list_regions(self, bank_name: str, pattern: str = None, pattern_type: str = None) -> QueryResult:
        """
        List regions for a specific bank, optionally filtered by pattern
        
        Args:
            bank_name: Name of the bank
            pattern: Optional pattern to filter regions
            pattern_type: Optional pattern type (auto-detect if None)
            
        Returns:
            QueryResult with list of regions
        """
        canonical, _, error = self._coerce_bank_name(bank_name)
        if canonical is None:
            return QueryResult(
                success=False,
                data=None,
                message=error
            )

        regions = list(self.data[canonical].get("region_to_code", {}).keys())
        
        if pattern:
            if pattern_type is None:
                pattern_type = self._detect_pattern_type(pattern)
            
            filtered_regions = [r for r in regions if self._match_pattern(r, pattern, pattern_type)]
            return QueryResult(
                success=True,
                data=filtered_regions,
                message=f"Found {len(filtered_regions)} matching region(s) out of {len(regions)} total"
            )
        
        return QueryResult(success=True, data=regions)
    
    def list_codes(self, bank_name: str, pattern: str = None, pattern_type: str = None) -> QueryResult:
        """
        List codes for a specific bank, optionally filtered by pattern
        
        Args:
            bank_name: Name of the bank
            pattern: Optional pattern to filter codes
            pattern_type: Optional pattern type (auto-detect if None)
            
        Returns:
            QueryResult with list of codes
        """
        canonical, _, error = self._coerce_bank_name(bank_name)
        if canonical is None:
            return QueryResult(
                success=False,
                data=None,
                message=error
            )

        codes = list(self.data[canonical].get("code_to_region", {}).keys())
        
        if pattern:
            if pattern_type is None:
                pattern_type = self._detect_pattern_type(pattern)
            
            filtered_codes = [c for c in codes if self._match_code(c, pattern, pattern_type)]
            return QueryResult(
                success=True,
                data=filtered_codes,
                message=f"Found {len(filtered_codes)} matching code(s) out of {len(codes)} total"
            )
        
        return QueryResult(success=True, data=codes)
    
    def get_statistics(self) -> Dict:
        """Get statistics about the data"""
        total_regions = sum(len(d.get("region_to_code", {})) for d in self.data.values())
        total_codes = sum(len(d.get("code_to_region", {})) for d in self.data.values())
        
        return {
            "total_banks": len(self.bank_list),
            "total_region_mappings": total_regions,
            "total_code_mappings": total_codes,
            "banks": self.bank_list
        }
    
    def export_data(self, output_file: str, bank_name: Optional[str] = None) -> bool:
        """
        Export data for a specific bank or all banks
        
        Args:
            output_file: Path to output JSON file
            bank_name: Optional specific bank name
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if bank_name:
                canonical = self.resolve_bank_name(bank_name)
                if canonical is None:
                    return False
                export_data = {canonical: self.data[canonical]}
            else:
                export_data = self.data
            
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False