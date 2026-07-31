from shopee_agent.shopee import (
    ConfigError,
    ShopeeClient,
    ShopeeConfig,
    ShopeeResponse,
    build_shop_authorization_url,
    load_config,
    main,
    sign_request,
    unix_timestamp,
)


def test_shopee_namespace_exports():
    assert ShopeeClient.__name__ == "ShopeeClient"
    assert ShopeeConfig.__name__ == "ShopeeConfig"
    assert ShopeeResponse.__name__ == "ShopeeResponse"
    assert ConfigError.__name__ == "ConfigError"
    assert callable(build_shop_authorization_url)
    assert callable(load_config)
    assert callable(main)
    assert callable(sign_request)
    assert callable(unix_timestamp)
