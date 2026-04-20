import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.vinted.it/member/signup/select_type?ref_url=%2Fitems%2Fnew")
    page.get_by_role("button", name="Accetta tutti").click()
    page.get_by_role("button", name="Accetta tutti").click()
    page.get_by_role("textbox", name="Email or phone").click()
    page.get_by_role("textbox", name="Email or phone").dblclick()
    page.get_by_role("textbox", name="Email or phone").fill("lucafaziobet@gmail.com")
    page.get_by_role("textbox", name="Email or phone").press("Enter")
    page.goto("https://www.vinted.it/member/signup/select_type?ref_url=%2Fitems%2Fnew")

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
