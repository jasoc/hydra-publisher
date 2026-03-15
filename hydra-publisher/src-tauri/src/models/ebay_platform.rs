use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use crate::models::article::Article;
use crate::models::platform::Platform;

/// eBay Inventory API provider.
///
/// Authentication: OAuth 2.0 User Token with `sell.inventory` scope.
/// The token must be obtained via eBay's OAuth flow and configured in Settings.
///
/// Flow for publish():
///   1. Create/replace an InventoryItem (SKU = article id)
///   2. Create an Offer for the InventoryItem on the EBAY_IT (or configured) marketplace
///   3. Publish the Offer → returns a listingId
///
/// Flow for update():
///   1. Update the InventoryItem (same PUT endpoint, idempotent)
///   2. Retrieve the existing offerId for this SKU, then PUT to update it
///   3. The Offer is already published, so no re-publish is needed unless
///      price/title changed — in that case eBay re-syncs automatically.
pub struct EbayPlatform {
    pub token: String,
    /// eBay marketplace ID, e.g. "EBAY_IT", "EBAY_US", "EBAY_DE"
    pub marketplace_id: String,
}

impl EbayPlatform {
    pub fn new(token: String, marketplace_id: String) -> Self {
        Self { token, marketplace_id }
    }

    fn build_inventory_item(&self, article: &Article) -> serde_json::Value {
        // Upload photos as base64 inline images (EPS Gallery API not used here;
        // for simplicity we embed up to the first photo as a product image URL-style payload)
        let image_urls: Vec<serde_json::Value> = article
            .photos
            .iter()
            .take(12) // eBay allows up to 12 images
            .map(|photo| {
                let path = std::path::Path::new(&article.folder_path).join(photo);
                // In production you would upload these to a CDN / eBay EPS gallery.
                // Here we use the local file URI as placeholder; a real impl would
                // upload to EPS first and use the returned URL.
                serde_json::json!(path.to_string_lossy())
            })
            .collect();

        serde_json::json!({
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": 1
                }
            },
            "condition": "USED_EXCELLENT",
            "product": {
                "title": article.name,
                "description": article.description,
                "imageUrls": image_urls
            }
        })
    }

    fn build_offer(&self, article: &Article, sku: &str) -> serde_json::Value {
        let price = article.price.unwrap_or(0.0);
        serde_json::json!({
            "sku": sku,
            "marketplaceId": self.marketplace_id,
            "format": "FIXED_PRICE",
            "availableQuantity": 1,
            "categoryId": "9800", // generic category; should be made configurable
            "listingDescription": article.description,
            "listingPolicies": {
                // These IDs must be set up in eBay Seller Hub and configured here
                "fulfillmentPolicyId": "",
                "paymentPolicyId": "",
                "returnPolicyId": ""
            },
            "pricingSummary": {
                "price": {
                    "currency": "EUR",
                    "value": format!("{:.2}", price)
                }
            }
        })
    }

    fn auth_header(&self) -> String {
        format!("Bearer {}", self.token)
    }

    
    /// POST /sell/inventory/v1/inventory_item/{sku}
    fn upsert_inventory_item(&self, article: &Article) -> Result<(), String> {
        let sku = &article.id;
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/inventory_item/{}",
            urlencoding::encode(sku)
        );
        let body = self.build_inventory_item(article);

        let client = reqwest::blocking::Client::new();
        let response = client
            .put(&url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .header("Content-Language", "it-IT")
            .json(&body)
            .send()
            .map_err(|e| format!("eBay inventory request failed: {}", e))?;

        if response.status().is_success() || response.status().as_u16() == 204 {
            Ok(())
        } else {
            let status = response.status();
            let body = response.text().unwrap_or_default();
            Err(format!("eBay inventory error {}: {}", status, body))
        }
    }

    /// POST /sell/inventory/v1/offer → returns offerId
    fn create_offer(&self, article: &Article) -> Result<String, String> {
        let url = "https://api.ebay.com/sell/inventory/v1/offer";
        let body = self.build_offer(article, &article.id);

        let client = reqwest::blocking::Client::new();
        let response = client
            .post(url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .json(&body)
            .send()
            .map_err(|e| format!("eBay create offer failed: {}", e))?;

        if response.status().is_success() {
            let json: serde_json::Value = response
                .json()
                .map_err(|e| format!("eBay offer parse error: {}", e))?;
            json["offerId"]
                .as_str()
                .map(|s| s.to_string())
                .ok_or_else(|| "eBay offer response missing offerId".to_string())
        } else {
            let status = response.status();
            let body = response.text().unwrap_or_default();
            Err(format!("eBay create offer error {}: {}", status, body))
        }
    }

    /// POST /sell/inventory/v1/offer/{offerId}/publish
    fn publish_offer(&self, offer_id: &str) -> Result<(), String> {
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/offer/{}/publish",
            offer_id
        );

        let client = reqwest::blocking::Client::new();
        let response = client
            .post(&url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .send()
            .map_err(|e| format!("eBay publish offer failed: {}", e))?;

        if response.status().is_success() {
            Ok(())
        } else {
            let status = response.status();
            let body = response.text().unwrap_or_default();
            Err(format!("eBay publish offer error {}: {}", status, body))
        }
    }

    /// GET /sell/inventory/v1/offer?sku={sku} → returns first offerId for this SKU
    fn find_offer_id(&self, sku: &str) -> Result<Option<String>, String> {
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/offer?sku={}",
            urlencoding::encode(sku)
        );

        let client = reqwest::blocking::Client::new();
        let response = client
            .get(&url)
            .header(AUTHORIZATION, self.auth_header())
            .send()
            .map_err(|e| format!("eBay find offer failed: {}", e))?;

        if response.status().is_success() {
            let json: serde_json::Value = response
                .json()
                .map_err(|e| format!("eBay offer list parse error: {}", e))?;
            let offer_id = json["offers"]
                .as_array()
                .and_then(|arr| arr.first())
                .and_then(|o| o["offerId"].as_str())
                .map(|s| s.to_string());
            Ok(offer_id)
        } else if response.status().as_u16() == 404 {
            Ok(None)
        } else {
            let status = response.status();
            let body = response.text().unwrap_or_default();
            Err(format!("eBay find offer error {}: {}", status, body))
        }
    }

    /// PUT /sell/inventory/v1/offer/{offerId}
    fn update_offer(&self, offer_id: &str, article: &Article) -> Result<(), String> {
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/offer/{}",
            offer_id
        );
        let body = self.build_offer(article, &article.id);

        let client = reqwest::blocking::Client::new();
        let response = client
            .put(&url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .json(&body)
            .send()
            .map_err(|e| format!("eBay update offer failed: {}", e))?;

        if response.status().is_success() || response.status().as_u16() == 204 {
            Ok(())
        } else {
            let status = response.status();
            let body = response.text().unwrap_or_default();
            Err(format!("eBay update offer error {}: {}", status, body))
        }
    }
}

impl Platform for EbayPlatform {
    fn id(&self) -> &str {
        "ebay"
    }

    fn name(&self) -> &str {
        "eBay"
    }

    fn publish(&self, article: &Article) -> Result<(), String> {
        if self.token.is_empty() {
            return Err("eBay OAuth token not configured".to_string());
        }

        self.upsert_inventory_item(article)?;
        let offer_id = self.create_offer(article)?;
        self.publish_offer(&offer_id)?;

        println!(
            "[eBay] Published article '{}' (id: {})",
            article.name, article.id
        );
        Ok(())
    }

    fn update(&self, article: &Article) -> Result<(), String> {
        if self.token.is_empty() {
            return Err("eBay OAuth token not configured".to_string());
        }

        // Update inventory item (idempotent PUT)
        self.upsert_inventory_item(article)?;

        // Update the existing offer if there is one
        if let Some(offer_id) = self.find_offer_id(&article.id)? {
            self.update_offer(&offer_id, article)?;
        }

        println!(
            "[eBay] Updated article '{}' (id: {})",
            article.name, article.id
        );
        Ok(())
    }
}
