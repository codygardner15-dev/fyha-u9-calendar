def table_is_tentative(table):
    # Check table caption and first two rows first
    internal_parts = []
    caption = table.find("caption")
    if caption is not None:
        internal_parts.append(caption.get_text(" ", strip=True))
    for row in table.find_all("tr")[:2]:
        internal_parts.append(row.get_text(" ", strip=True))
    if "TENTATIVE" in " ".join(internal_parts).upper():
        return True

    # Walk backwards through preceding elements until hitting an earlier table
    for el in table.find_all_previous():
        if el is table:
            continue
        if el.name == "table" or any(t is not table for t in el.find_all("table")):
            break
        text = " ".join(el.get_text(" ", strip=True).split())
        if not text:
            continue
        # Only inspect headings/banners/rows that look like a week header or carry TENTATIVE
        if "TENTATIVE" in text.upper() and DATE_BANNER_RE.search(text):
            return True
        if DATE_BANNER_RE.search(text) and "TENTATIVE" not in text.upper():
            return False

    return False
