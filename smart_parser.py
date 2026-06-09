import re
from datetime import datetime, timezone, timedelta

try:
    import dateparser
    HAS_DATEPARSER = True
except ImportError:
    HAS_DATEPARSER = False

IST = timezone(timedelta(hours=5, minutes=30))

VALID_PRIORITIES = ['low', 'medium', 'high']
VALID_CATEGORIES = ['general', 'work', 'personal', 'study', 'health', 'finance', 'shopping', 'other']

# Common relative date phrases to help extract date portions from text
DATE_KEYWORDS = [
    'today', 'tonight', 'tomorrow', 'yesterday',
    'next monday', 'next tuesday', 'next wednesday', 'next thursday',
    'next friday', 'next saturday', 'next sunday',
    'this monday', 'this tuesday', 'this wednesday', 'this thursday',
    'this friday', 'this saturday', 'this sunday',
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
    'next week', 'next month',
    'in \\d+ (?:minute|hour|day|week|month)s?',
    '\\d+ (?:minute|hour|day|week|month)s? (?:from now|later)',
]

# Time patterns
TIME_PATTERN = r'\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))\b'
DATE_PATTERN = r'\b(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b'


def parse_smart_input(text):
    """
    Parse natural language task input.
    
    Examples:
        "Finish report tomorrow 5pm #work !high"
        "Buy groceries #shopping !low"
        "Study chapter 5 next monday 3:30pm #study !medium"
        "Call dentist today 2pm #health"
    
    Returns dict with: title, due_date_str, category, priority, due_date_iso
    """
    if not text or not text.strip():
        return {
            'title': '',
            'due_date_str': '',
            'category': '',
            'priority': '',
            'due_date_iso': ''
        }

    original = text.strip()
    remaining = original

    # ── 1. Extract priority (!high, !medium, !low) ──
    priority = ''
    priority_match = re.search(r'!(low|medium|high)\b', remaining, re.IGNORECASE)
    if priority_match:
        priority = priority_match.group(1).lower()
        remaining = remaining[:priority_match.start()] + remaining[priority_match.end():]

    # ── 2. Extract category (#work, #study, etc.) ──
    category = ''
    category_match = re.search(r'#(\w+)', remaining)
    if category_match:
        raw_cat = category_match.group(1).lower()
        # Match against valid categories (fuzzy)
        for valid_cat in VALID_CATEGORIES:
            if raw_cat == valid_cat or raw_cat == valid_cat[:len(raw_cat)]:
                category = valid_cat.capitalize()
                break
        if not category:
            # Use the raw tag capitalized if no match
            category = raw_cat.capitalize()
        remaining = remaining[:category_match.start()] + remaining[category_match.end():]

    # ── 3. Extract date/time ──
    due_date_str = ''
    due_date_iso = ''

    # Try to find date+time phrases in the remaining text
    date_text, remaining = _extract_date_portion(remaining)

    if date_text and HAS_DATEPARSER:
        parsed_dt = dateparser.parse(
            date_text,
            settings={
                'PREFER_DATES_FROM': 'future',
                'RELATIVE_BASE': datetime.now(IST).replace(tzinfo=None),
                'RETURN_AS_TIMEZONE_AWARE': False
            }
        )
        if parsed_dt:
            due_date_str = date_text.strip()
            # Convert to ISO format for datetime-local input
            due_date_iso = parsed_dt.strftime('%Y-%m-%dT%H:%M')
    elif date_text and not HAS_DATEPARSER:
        # Basic fallback without dateparser
        due_date_str = date_text.strip()
        due_date_iso = _basic_date_parse(date_text)

    # ── 4. Clean up title ──
    title = re.sub(r'\s+', ' ', remaining).strip()
    # Remove trailing/leading punctuation artifacts
    title = title.strip(' ,-;:')

    return {
        'title': title,
        'due_date_str': due_date_str,
        'category': category,
        'priority': priority,
        'due_date_iso': due_date_iso
    }


def _extract_date_portion(text):
    """
    Extract the date/time portion from text, return (date_text, remaining_text).
    """
    lower = text.lower()
    best_match = None
    best_start = len(text)
    best_end = 0

    # Try matching known date keyword phrases
    for kw in DATE_KEYWORDS:
        pattern = r'\b(' + kw + r')\b'
        m = re.search(pattern, lower)
        if m:
            start = m.start()
            end = m.end()
            if start < best_start:
                best_start = start
                best_end = end
                best_match = True

    # Also look for explicit time patterns like "5pm", "3:30pm"
    time_match = re.search(TIME_PATTERN, lower)
    if time_match:
        if best_match is None:
            best_start = time_match.start()
        best_end = max(best_end, time_match.end())
        best_match = True

    # Look for date patterns like "12/25" or "12-25-2025"
    date_match = re.search(DATE_PATTERN, lower)
    if date_match:
        if best_match is None:
            best_start = date_match.start()
        best_end = max(best_end, date_match.end())
        best_match = True

    # Also check for "at <time>" pattern
    at_time = re.search(r'\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', lower, re.IGNORECASE)
    if at_time:
        if best_match is None:
            best_start = at_time.start()
        best_end = max(best_end, at_time.end())
        best_match = True

    if best_match:
        # Extend to capture the full date+time phrase
        # Include any time that follows the date keyword
        after_text = text[best_end:]
        extra_time = re.match(r'\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))', after_text)
        if extra_time:
            best_end += extra_time.end()

        # Also check for time before the date keyword
        before_text = text[:best_start]
        pre_time = re.search(r'(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))\s*$', before_text)
        if pre_time:
            best_start = pre_time.start()

        date_text = text[best_start:best_end].strip()
        remaining = (text[:best_start] + ' ' + text[best_end:]).strip()
        return date_text, remaining

    return '', text


def _basic_date_parse(date_text):
    """
    Basic fallback date parser when dateparser is not available.
    Handles 'today', 'tomorrow' + optional time.
    """
    now = datetime.now(IST).replace(tzinfo=None)
    lower = date_text.lower().strip()

    target_date = None
    if 'tomorrow' in lower:
        target_date = now + timedelta(days=1)
    elif 'today' in lower or 'tonight' in lower:
        target_date = now
    elif 'next week' in lower:
        target_date = now + timedelta(weeks=1)

    if target_date is None:
        return ''

    # Try to extract time
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', lower, re.IGNORECASE)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = time_match.group(3).lower()
        if ampm == 'pm' and hour != 12:
            hour += 12
        elif ampm == 'am' and hour == 12:
            hour = 0
        target_date = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        target_date = target_date.replace(hour=23, minute=59, second=0, microsecond=0)

    return target_date.strftime('%Y-%m-%dT%H:%M')
