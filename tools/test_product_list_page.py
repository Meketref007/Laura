"""Test: use Playwright to explore product listing page."""
import io, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from shopee_agent.seller_center_actions import SellerCenterActions

with SellerCenterActions() as actions:
    if not actions.is_authenticated():
        print("Nao autenticado")
        sys.exit(1)

    intc = actions._ensure_playwright()
    intc._page.goto(
        "https://seller.shopee.com.br/portal/product/listing",
        wait_until="domcontentloaded",
        timeout=30000,
    )
    time.sleep(5)

    # Extract product IDs from the page
    result = intc._page.evaluate("""() => {
  const ids = [];
  // Look for product edit links
  document.querySelectorAll('a').forEach(a => {
    const m = a.href.match(/\\/product\\/edit\\/(\\d+)/);
    if (m) ids.push(m[1]);
  });
  // Look for data attributes
  document.querySelectorAll('[data-item-id], [data-id]').forEach(el => {
    const id = el.getAttribute('data-item-id') || el.getAttribute('data-id');
    if (id && /^\\d+$/.test(id)) ids.push(id);
  });
  // Look for elements with item_id in classes or ids
  document.querySelectorAll('[id*="item"], [class*="item"], [class*="product"]').forEach(el => {
    const m = (el.id || '').match(/item[_-]?(\\d+)/i);
    if (m) ids.push(m[1]);
  });
  return [...new Set(ids)];
}""")

    print(f"Items found: {len(result)}")
    if result:
        print(f"IDs: {result[:30]}")
    else:
        # Debug: get page content
        title = intc._page.evaluate("() => document.title")
        print(f"Title: {title}")
        text = intc._page.evaluate("() => document.body.innerText.substring(0, 3000)")
        print(f"Body text:\n{text}")
        # Check for any fetch/XHR responses
        html = intc._page.evaluate("() => document.documentElement.outerHTML.substring(0, 2000)")
        print(f"\nHTML:\n{html}")
