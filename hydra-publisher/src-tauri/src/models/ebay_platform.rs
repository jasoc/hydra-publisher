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
    /// Business policy IDs from eBay Seller Hub → Account → Business Policies
    pub fulfillment_policy_id: String,
    pub payment_policy_id: String,
    pub return_policy_id: String,
    /// Default eBay leaf category ID used when article.category is not set.
    /// Find it at: https://www.ebay.it/sch/ — navigate to the desired category, copy the ID from the URL.
    pub default_category_id: String,
}

impl EbayPlatform {
    pub fn new(
        token: String,
        marketplace_id: String,
        fulfillment_policy_id: String,
        payment_policy_id: String,
        return_policy_id: String,
        default_category_id: String,
    ) -> Self {
        Self {
            token,
            marketplace_id,
            fulfillment_policy_id,
            payment_policy_id,
            return_policy_id,
            default_category_id,
        }
    }

    fn log(msg: &str) {
        println!("[eBay] {}", msg);
    }

    fn log_err(msg: &str) {
        eprintln!("[eBay][ERR] {}", msg);
    }

    fn log_step(step: u8, total: u8, msg: &str) {
        println!("[eBay] ({}/{}) {}", step, total, msg);
    }

    /// Logs a copy-pasteable curl command. Token is masked for safety.
    fn log_curl(method: &str, url: &str, extra_headers: &[(&str, &str)], body: Option<&serde_json::Value>) {
        let mut cmd = format!(
            "curl -s -X {} \\\n  '{}' \\\n  -H 'Authorization: Bearer <YOUR_TOKEN>' \\\n  -H 'Content-Type: application/json'",
            method, url
        );
        for (k, v) in extra_headers {
            cmd.push_str(&format!(" \\\n  -H '{}: {}'", k, v));
        }
        if let Some(b) = body {
            let pretty = serde_json::to_string_pretty(b).unwrap_or_default();
            cmd.push_str(&format!(" \\\n  -d '{}'", pretty.replace('\'', "'\"'\"'")));
        }
        println!("[eBay][CURL]\n{}", cmd);
    }

    /// Maps any free-text condition to a valid eBay condition enum.
    /// Accepts both Italian and English values, case-insensitive.
    /// eBay allowed values: NEW, LIKE_NEW, NEW_OTHER, NEW_WITH_DEFECTS,
    ///   CERTIFIED_REFURBISHED, EXCELLENT_REFURBISHED, VERY_GOOD_REFURBISHED,
    ///   GOOD_REFURBISHED, SELLER_REFURBISHED, USED_EXCELLENT, USED_VERY_GOOD,
    ///   USED_GOOD, USED_ACCEPTABLE, FOR_PARTS_OR_NOT_WORKING
    fn map_condition(raw: &str) -> &'static str {
        match raw.to_lowercase().trim() {
            // Global conditions (from article dropdown)
            "nuovo"                                     => "NEW",
            "usato - come nuovo"                        => "LIKE_NEW",
            "usato - buono"                             => "USED_GOOD",
            "usato - accettabile"                       => "USED_ACCEPTABLE",
            // Legacy / already valid eBay enum values
            "new"                                       => "NEW",
            "like_new" | "come nuovo" | "come_nuovo"   => "LIKE_NEW",
            "new_other"                                 => "NEW_OTHER",
            "new_with_defects"                          => "NEW_WITH_DEFECTS",
            "certified_refurbished"                     => "CERTIFIED_REFURBISHED",
            "excellent_refurbished"                     => "EXCELLENT_REFURBISHED",
            "very_good_refurbished"                     => "VERY_GOOD_REFURBISHED",
            "good_refurbished"                          => "GOOD_REFURBISHED",
            "seller_refurbished" | "ricondizionato"     => "SELLER_REFURBISHED",
            "used_excellent" | "ottimo"                 => "USED_EXCELLENT",
            "used_very_good" | "molto buono"
                | "molto_buono"                         => "USED_VERY_GOOD",
            "used_good" | "buono"                       => "USED_GOOD",
            "used_acceptable" | "accettabile"           => "USED_ACCEPTABLE",
            "for_parts_or_not_working"
                | "per ricambi" | "non funzionante"     => "FOR_PARTS_OR_NOT_WORKING",
            // Default
            _                                           => "USED_EXCELLENT",
        }
    }

    /// Uploads a local image file to eBay EPS (eBay Picture Services) via the
    /// Trading API `UploadSiteHostedPictures` call and returns the hosted HTTPS URL.
    fn upload_image_to_eps(&self, image_path: &str) -> Result<String, String> {
        let image_data = std::fs::read(image_path)
            .map_err(|e| format!("Cannot read image '{}': {}", image_path, e))?;

        let size_kb = image_data.len() / 1024;

        let file_name = std::path::Path::new(image_path)
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();

        Self::log(&format!("  Uploading image '{}' ({}KB) to EPS...", file_name, size_kb));

        let mime_type = if file_name.to_lowercase().ends_with(".png") {
            "image/png"
        } else if file_name.to_lowercase().ends_with(".gif") {
            "image/gif"
        } else {
            "image/jpeg"
        };

        // eBay Trading API site ID derived from marketplace
        let site_id = match self.marketplace_id.as_str() {
            "EBAY_IT" => "101",
            "EBAY_DE" => "77",
            "EBAY_FR" => "71",
            "EBAY_ES" => "186",
            "EBAY_UK" => "3",
            _ => "0", // EBAY_US default
        };

        let safe_name = file_name
            .replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;");

        let xml_payload = format!(
            r#"<?xml version="1.0" encoding="utf-8"?>
<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <PictureName>{name}</PictureName>
  <PictureSet>Supersize</PictureSet>
</UploadSiteHostedPicturesRequest>"#,
            token = self.token,
            name = safe_name
        );

        let xml_part = reqwest::blocking::multipart::Part::text(xml_payload)
            .mime_str("text/xml;charset=utf-8")
            .map_err(|e| format!("EPS XML part error: {}", e))?;

        let image_part = reqwest::blocking::multipart::Part::bytes(image_data)
            .file_name(file_name.clone())
            .mime_str(mime_type)
            .map_err(|e| format!("EPS image part error: {}", e))?;

        let form = reqwest::blocking::multipart::Form::new()
            .part("XML Payload", xml_part)
            .part("image", image_part);

        let client = reqwest::blocking::Client::new();
        let response = client
            .post("https://api.ebay.com/ws/api.dll")
            .header("X-EBAY-API-CALL-NAME", "UploadSiteHostedPictures")
            .header("X-EBAY-API-SITEID", site_id)
            .header("X-EBAY-API-VERSION", "1155")
            .header("X-EBAY-API-IAF-TOKEN", &self.token)
            .multipart(form)
            .send()
            .map_err(|e| format!("EPS upload request failed: {}", e))?;

        let body = response
            .text()
            .map_err(|e| format!("EPS response read error: {}", e))?;

        // Extract <FullURL>...</FullURL> from the XML response
        if let (Some(start), Some(end)) = (body.find("<FullURL>"), body.find("</FullURL>")) {
            let url = body[start + 9..end].trim().to_string();
            if !url.is_empty() {
                Self::log(&format!("  Image uploaded OK → {}", url));
                return Ok(url);
            }
        }

        // Extract <LongMessage> for a more useful error
        let ebay_msg = if let (Some(s), Some(e)) = (body.find("<LongMessage>"), body.find("</LongMessage>")) {
            body[s + 13..e].trim().to_string()
        } else {
            body[..body.len().min(400)].to_string()
        };

        Err(format!("EPS upload failed for '{}': {}", file_name, ebay_msg))
    }

    fn build_inventory_item(&self, article: &Article) -> serde_json::Value {
        let total = article.photos.len().min(12);
        Self::log(&format!(
            "Uploading {}/{} photos to eBay EPS for SKU '{}'...",
            total,
            article.photos.len(),
            article.id
        ));

        let image_urls: Vec<serde_json::Value> = article
            .photos
            .iter()
            .take(12)
            .enumerate()
            .filter_map(|(i, photo)| {
                let path = std::path::Path::new(&article.folder_path)
                    .join(photo)
                    .to_string_lossy()
                    .to_string();
                Self::log(&format!("  [{}/{}] {}", i + 1, total, photo));
                match self.upload_image_to_eps(&path) {
                    Ok(url) => Some(serde_json::json!(url)),
                    Err(e) => {
                        Self::log_err(&format!("  Skipping '{}': {}", photo, e));
                        None
                    }
                }
            })
            .collect();

        Self::log(&format!("{}/{} images uploaded successfully", image_urls.len(), total));

        let condition = Self::map_condition(article.condition.as_deref().unwrap_or(""));

        Self::log(&format!(
            "Building inventory item: title='{}' condition='{}' images={}",
            article.name,
            condition,
            image_urls.len()
        ));

        let mut product = serde_json::json!({
            "title": article.name,
            "description": article.description,
        });

        if !image_urls.is_empty() {
            product["imageUrls"] = serde_json::json!(image_urls);
        }

        serde_json::json!({
            "availability": {
                "shipToLocationAvailability": { "quantity": 1 }
            },
            "condition": condition,
            "product": product
        })
    }

    fn build_offer(&self, article: &Article, sku: &str) -> serde_json::Value {
        let price = article.price.unwrap_or(0.0);
        let currency = match self.marketplace_id.as_str() {
            "EBAY_UK" => "GBP",
            "EBAY_US" => "USD",
            _ => "EUR",
        };
        // article.category may contain a display name (e.g. "Casa e giardino") rather than
        // a numeric eBay category ID. Use it only when it is entirely numeric.
        let article_category = article
            .category
            .as_deref()
            .filter(|s| !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()));

        let category = article_category
            .or_else(|| {
                let c = self.default_category_id.as_str();
                if c.is_empty() { None } else { Some(c) }
            })
            .ok_or_else(|| {
                "No numeric category ID set: configure 'eBay Default Category ID' in Settings".to_string()
            });
        let category = match category {
            Ok(c) => c.to_string(),
            Err(e) => { Self::log_err(&e); String::new() }
        };

        Self::log(&format!(
            "Building offer: SKU='{}' marketplace='{}' price={:.2}{} category='{}' fulfillment='{}' payment='{}' return='{}'",
            sku, self.marketplace_id, price, currency, category,
            self.fulfillment_policy_id, self.payment_policy_id, self.return_policy_id
        ));

        serde_json::json!({
            "sku": sku,
            "marketplaceId": self.marketplace_id,
            "format": "FIXED_PRICE",
            "availableQuantity": 1,
            "categoryId": category,
            "listingDescription": article.description,
            "merchantLocationKey": "hydra-default",
            "listingPolicies": {
                "fulfillmentPolicyId": self.fulfillment_policy_id,
                "paymentPolicyId": self.payment_policy_id,
                "returnPolicyId": self.return_policy_id
            },
            "pricingSummary": {
                "price": {
                    "currency": currency,
                    "value": format!("{:.2}", price)
                }
            }
        })
    }

    fn auth_header(&self) -> String {
        format!("Bearer {}", self.token)
    }

    fn content_language(&self) -> &'static str {
        match self.marketplace_id.as_str() {
            "EBAY_IT" => "it-IT",
            "EBAY_DE" => "de-DE",
            "EBAY_FR" => "fr-FR",
            "EBAY_ES" => "es-ES",
            "EBAY_UK" => "en-GB",
            _ => "en-US",
        }
    }

    fn country_code(&self) -> &'static str {
        match self.marketplace_id.as_str() {
            "EBAY_IT" => "IT",
            "EBAY_DE" => "DE",
            "EBAY_FR" => "FR",
            "EBAY_ES" => "ES",
            "EBAY_UK" => "GB",
            _ => "US",
        }
    }

    /// Ensures a default merchant location exists on eBay.
    /// Uses a fixed locationKey "hydra-default". If eBay returns 409 (already exists), that's fine.
    fn ensure_merchant_location(&self) -> Result<(), String> {
        let key = "hydra-default";
        let url = format!("https://api.ebay.com/sell/inventory/v1/location/{}", key);

        let body = serde_json::json!({
            "location": {
                "address": {
                    "country": self.country_code(),
                    "stateOrProvince": "Catania",
                    "city": "Mascalucia"
                }
            },
            "locationTypes": ["WAREHOUSE"],
            "name": "Hydra Publisher Default"
        });

        let client = reqwest::blocking::Client::new();
        let response = client
            .post(&url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .json(&body)
            .send()
            .map_err(|e| format!("Merchant location request failed: {}", e))?;

        let status = response.status().as_u16();
        let body = response.text().unwrap_or_default();
        match status {
            200 | 201 | 204 => {
                Self::log(&format!("Merchant location '{}' created OK", key));
                Ok(())
            }
            // eBay returns 409 OR 400 with errorId 25803 when the location already exists
            409 => {
                Self::log(&format!("Merchant location '{}' already exists — OK", key));
                Ok(())
            }
            400 if body.contains("25803") || body.contains("already exists") => {
                Self::log(&format!("Merchant location '{}' already exists — OK", key));
                Ok(())
            }
            _ => {
                let msg = format!("Merchant location creation failed (HTTP {}): {}", status, body);
                Self::log_err(&msg);
                Err(msg)
            }
        }
    }

    /// PUT /sell/inventory/v1/inventory_item/{sku}
    fn upsert_inventory_item(&self, article: &Article) -> Result<(), String> {
        let sku = &article.id;
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/inventory_item/{}",
            urlencoding::encode(sku)
        );

        Self::log(&format!("PUT inventory item → {}", url));
        let body = self.build_inventory_item(article);
        Self::log_curl("PUT", &url, &[("Content-Language", self.content_language())], Some(&body));

        let client = reqwest::blocking::Client::new();
        let response = client
            .put(&url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .header("Content-Language", self.content_language())
            .json(&body)
            .send()
            .map_err(|e| format!("eBay inventory request failed: {}", e))?;

        let status = response.status();
        if status.is_success() || status.as_u16() == 204 {
            Self::log(&format!("Inventory item upserted OK (HTTP {})", status.as_u16()));
            Ok(())
        } else {
            let body = response.text().unwrap_or_default();
            let msg = format!("Inventory upsert failed (HTTP {}): {}", status, body);
            Self::log_err(&msg);
            Err(msg)
        }
    }

    /// POST /sell/inventory/v1/offer → returns offerId
    fn create_offer(&self, article: &Article) -> Result<String, String> {
        let url = "https://api.ebay.com/sell/inventory/v1/offer";
        Self::log(&format!("POST create offer → {}", url));

        let body = self.build_offer(article, &article.id);
        Self::log_curl("POST", url, &[("Content-Language", self.content_language())], Some(&body));

        let client = reqwest::blocking::Client::new();
        let response = client
            .post(url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .header("Content-Language", self.content_language())
            .json(&body)
            .send()
            .map_err(|e| format!("eBay create offer request failed: {}", e))?;

        let status = response.status();
        if status.is_success() {
            let json: serde_json::Value = response
                .json()
                .map_err(|e| format!("eBay offer parse error: {}", e))?;
            let offer_id = json["offerId"]
                .as_str()
                .map(|s| s.to_string())
                .ok_or_else(|| format!("Offer response missing offerId. Full response: {}", json))?;
            Self::log(&format!("Offer created OK → offerId='{}'", offer_id));
            Ok(offer_id)
        } else {
            let body = response.text().unwrap_or_default();
            let msg = format!("Create offer failed (HTTP {}): {}", status, body);
            Self::log_err(&msg);
            Err(msg)
        }
    }

    /// POST /sell/inventory/v1/offer/{offerId}/publish → returns listingId
    fn publish_offer(&self, offer_id: &str) -> Result<String, String> {
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/offer/{}/publish",
            offer_id
        );

        // GET the offer first so we can log exactly what eBay has stored
        // (categoryId, status, etc.) before attempting to publish.
        {
            let get_url = format!("https://api.ebay.com/sell/inventory/v1/offer/{}", offer_id);
            let c = reqwest::blocking::Client::new();
            match c.get(&get_url).header(AUTHORIZATION, self.auth_header()).send() {
                Ok(r) => match r.json::<serde_json::Value>() {
                    Ok(j) => Self::log(&format!(
                        "Offer state before publish (categoryId='{}' status='{}'):\n{}",
                        j["categoryId"].as_str().unwrap_or("MISSING"),
                        j["status"].as_str().unwrap_or("?"),
                        serde_json::to_string_pretty(&j).unwrap_or_default()
                    )),
                    Err(e) => Self::log_err(&format!("Could not parse offer GET response: {}", e)),
                },
                Err(e) => Self::log_err(&format!("Could not GET offer before publish: {}", e)),
            }
        }

        Self::log(&format!("POST publish offer → {}", url));
        Self::log_curl("POST", &url, &[], None);

        let client = reqwest::blocking::Client::new();
        let response = client
            .post(&url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .send()
            .map_err(|e| format!("eBay publish offer request failed: {}", e))?;

        let status = response.status();
        if status.is_success() {
            let json: serde_json::Value = response
                .json()
                .map_err(|e| format!("eBay publish offer parse error: {}", e))?;
            let listing_id = json["listingId"]
                .as_str()
                .unwrap_or("unknown")
                .to_string();
            Self::log(&format!("Offer published OK → listingId='{}'", listing_id));
            Ok(listing_id)
        } else {
            let body = response.text().unwrap_or_default();
            let msg = format!("Publish offer failed (HTTP {}): {}", status, body);
            Self::log_err(&msg);
            Err(msg)
        }
    }

    /// GET /sell/inventory/v1/offer?sku={sku} → returns first offerId for this SKU
    fn find_offer_id(&self, sku: &str) -> Result<Option<String>, String> {
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/offer?sku={}",
            urlencoding::encode(sku)
        );
        Self::log(&format!("GET existing offer for SKU='{}' → {}", sku, url));
        Self::log_curl("GET", &url, &[], None);

        let client = reqwest::blocking::Client::new();
        let response = client
            .get(&url)
            .header(AUTHORIZATION, self.auth_header())
            .send()
            .map_err(|e| format!("eBay find offer request failed: {}", e))?;

        let status = response.status();
        if status.is_success() {
            let json: serde_json::Value = response
                .json()
                .map_err(|e| format!("eBay offer list parse error: {}", e))?;
            let offer_id = json["offers"]
                .as_array()
                .and_then(|arr| arr.first())
                .and_then(|o| o["offerId"].as_str())
                .map(|s| s.to_string());
            match &offer_id {
                Some(id) => Self::log(&format!("Found existing offer → offerId='{}'", id)),
                None => Self::log("No existing offer found for this SKU"),
            }
            Ok(offer_id)
        } else if status.as_u16() == 404 {
            Self::log("No existing offer found (404)");
            Ok(None)
        } else {
            let body = response.text().unwrap_or_default();
            let msg = format!("Find offer failed (HTTP {}): {}", status, body);
            Self::log_err(&msg);
            Err(msg)
        }
    }

    /// PUT /sell/inventory/v1/offer/{offerId}
    fn update_offer(&self, offer_id: &str, article: &Article) -> Result<(), String> {
        let url = format!(
            "https://api.ebay.com/sell/inventory/v1/offer/{}",
            offer_id
        );
        Self::log(&format!("PUT update offer '{}' → {}", offer_id, url));

        let body = self.build_offer(article, &article.id);
        Self::log_curl("PUT", &url, &[("Content-Language", self.content_language())], Some(&body));

        let client = reqwest::blocking::Client::new();
        let response = client
            .put(&url)
            .header(AUTHORIZATION, self.auth_header())
            .header(CONTENT_TYPE, "application/json")
            .header("Content-Language", self.content_language())
            .json(&body)
            .send()
            .map_err(|e| format!("eBay update offer request failed: {}", e))?;

        let status = response.status();
        if status.is_success() || status.as_u16() == 204 {
            Self::log(&format!("Offer updated OK (HTTP {})", status.as_u16()));
            Ok(())
        } else {
            let body = response.text().unwrap_or_default();
            let msg = format!("Update offer failed (HTTP {}): {}", status, body);
            Self::log_err(&msg);
            Err(msg)
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
        if self.fulfillment_policy_id.is_empty() || self.payment_policy_id.is_empty() || self.return_policy_id.is_empty() {
            return Err("eBay business policy IDs not configured — open Settings and click Auto-fetch".to_string());
        }

        EbayPlatform::log(&format!(
            "=== PUBLISH START: '{}' (SKU: {}) ===",
            article.name, article.id
        ));

        // 1. Upsert inventory item
        EbayPlatform::log_step(1, 3, "Upserting inventory item...");
        self.upsert_inventory_item(article)?;

        // 2. Ensure merchant location exists, then resolve offer
        EbayPlatform::log_step(2, 3, "Resolving offer...");
        self.ensure_merchant_location()?;
        let offer_id = match self.find_offer_id(&article.id)? {
            Some(id) => {
                EbayPlatform::log(&format!("Existing offer found ({}), updating it...", id));
                self.update_offer(&id, article)?;
                id
            }
            None => {
                EbayPlatform::log("No existing offer, creating new one...");
                self.create_offer(article)?
            }
        };

        // 3. Publish → get listingId
        EbayPlatform::log_step(3, 3, "Publishing offer...");
        let listing_id = self.publish_offer(&offer_id)?;

        let domain = match self.marketplace_id.as_str() {
            "EBAY_IT" => "ebay.it",
            "EBAY_DE" => "ebay.de",
            "EBAY_FR" => "ebay.fr",
            "EBAY_ES" => "ebay.es",
            "EBAY_UK" => "ebay.co.uk",
            _ => "ebay.com",
        };

        EbayPlatform::log(&format!(
            "=== PUBLISH OK: '{}' → https://www.{}/itm/{} ===",
            article.name, domain, listing_id
        ));
        Ok(())
    }

    fn update(&self, article: &Article) -> Result<(), String> {
        if self.token.is_empty() {
            return Err("eBay OAuth token not configured".to_string());
        }
        if self.fulfillment_policy_id.is_empty() || self.payment_policy_id.is_empty() || self.return_policy_id.is_empty() {
            return Err("eBay business policy IDs not configured — open Settings and click Auto-fetch".to_string());
        }

        EbayPlatform::log(&format!(
            "=== UPDATE START: '{}' (SKU: {}) ===",
            article.name, article.id
        ));

        // 1. Upsert inventory item
        EbayPlatform::log_step(1, 3, "Updating inventory item...");
        self.upsert_inventory_item(article)?;

        // 2. Update existing offer or create a new one if missing
        EbayPlatform::log_step(2, 3, "Resolving offer...");
        self.ensure_merchant_location()?;
        let offer_id = match self.find_offer_id(&article.id)? {
            Some(id) => {
                EbayPlatform::log(&format!("Existing offer found ({}), updating it...", id));
                self.update_offer(&id, article)?;
                id
            }
            None => {
                EbayPlatform::log("No existing offer found — creating a new one...");
                self.create_offer(article)?
            }
        };

        // 3. Publish (idempotent: re-syncs if already live, publishes if new)
        EbayPlatform::log_step(3, 3, "Publishing offer...");
        let listing_id = self.publish_offer(&offer_id)?;

        let domain = match self.marketplace_id.as_str() {
            "EBAY_IT" => "ebay.it",
            "EBAY_DE" => "ebay.de",
            "EBAY_FR" => "ebay.fr",
            "EBAY_ES" => "ebay.es",
            "EBAY_UK" => "ebay.co.uk",
            _ => "ebay.com",
        };

        EbayPlatform::log(&format!(
            "=== UPDATE OK: '{}' → https://www.{}/itm/{} ===",
            article.name, domain, listing_id
        ));
        Ok(())
    }
}
