def test_scraper_imports():
    import Scraper

    assert "top" in Scraper.TIER_LIST_URLS
    assert callable(Scraper.get_build)
