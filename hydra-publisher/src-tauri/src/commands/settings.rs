use tauri::AppHandle;
use tauri_plugin_store::StoreExt;
use serde::{Deserialize, Serialize};
use crate::models::settings::AppSettings;

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EbayPolicies {
    pub fulfillment_policy_id: String,
    pub fulfillment_policy_name: String,
    pub payment_policy_id: String,
    pub payment_policy_name: String,
    pub return_policy_id: String,
    pub return_policy_name: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct EbayCategorySuggestion {
    pub category_id: String,
    pub category_name: String,
    pub category_path: String, // breadcrumb, e.g. "Casa e arredamento > Mobili > Comodini"
}

/// Searches eBay leaf categories using the Taxonomy API.
#[tauri::command]
pub async fn search_ebay_categories(
    token: String,
    marketplace_id: String,
    query: String,
) -> Result<Vec<EbayCategorySuggestion>, String> {
    // Category tree IDs per marketplace
    let tree_id = match marketplace_id.as_str() {
        "EBAY_IT" => "101",
        "EBAY_DE" => "77",
        "EBAY_FR" => "71",
        "EBAY_ES" => "186",
        "EBAY_UK" => "3",
        _ => "0",
    };

    let url = format!(
        "https://api.ebay.com/commerce/taxonomy/v1/category_tree/{}/get_category_suggestions?q={}",
        tree_id,
        urlencoding::encode(&query)
    );

    let client = reqwest::Client::new();
    let resp = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token))
        .send()
        .await
        .map_err(|e| format!("Taxonomy request failed: {}", e))?;

    if !resp.status().is_success() {
        let status = resp.status();
        let body = resp.text().await.unwrap_or_default();
        return Err(format!("Taxonomy API error {}: {}", status, body));
    }

    let json: serde_json::Value = resp
        .json()
        .await
        .map_err(|e| format!("Taxonomy parse error: {}", e))?;

    let suggestions = json["categorySuggestions"]
        .as_array()
        .ok_or_else(|| "No categorySuggestions in response".to_string())?;

    let results: Vec<EbayCategorySuggestion> = suggestions
        .iter()
        .filter_map(|s| {
            let cat = &s["category"];
            let id = cat["categoryId"].as_str()?.to_string();
            let name = cat["categoryName"].as_str()?.to_string();

            // Build breadcrumb from ancestors (root → leaf)
            let mut path_parts: Vec<String> = s["categoryTreeNodeAncestors"]
                .as_array()
                .map(|ancestors| {
                    let mut parts: Vec<(i64, String)> = ancestors
                        .iter()
                        .filter_map(|a| {
                            let level = a["ancestorCategoryTreeNodeLevel"].as_i64()?;
                            let aname = a["ancestorCategoryName"].as_str()?.to_string();
                            Some((level, aname))
                        })
                        .collect();
                    parts.sort_by_key(|(level, _)| *level);
                    parts.into_iter().map(|(_, n)| n).collect()
                })
                .unwrap_or_default();
            path_parts.push(name.clone());
            let category_path = path_parts.join(" > ");

            Some(EbayCategorySuggestion { category_id: id, category_name: name, category_path })
        })
        .take(20)
        .collect();

    Ok(results)
}

#[tauri::command]
pub async fn get_settings(app: AppHandle) -> Result<AppSettings, String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    match store.get("settings") {
        Some(value) => serde_json::from_value(value.clone()).map_err(|e| e.to_string()),
        None => Ok(AppSettings::default()),
    }
}

#[tauri::command]
pub async fn save_settings(app: AppHandle, settings: AppSettings) -> Result<(), String> {
    let store = app.store("settings.json").map_err(|e| e.to_string())?;
    let value = serde_json::to_value(&settings).map_err(|e| e.to_string())?;
    store.set("settings", value);
    store.save().map_err(|e| e.to_string())?;
    Ok(())
}

/// Fetches the first fulfillment, payment and return policy IDs from the eBay
/// Account API for the given marketplace, using the provided OAuth token.
#[tauri::command]
pub async fn fetch_ebay_policies(
    token: String,
    marketplace_id: String,
) -> Result<EbayPolicies, String> {
    let client = reqwest::Client::new();
    let auth = format!("Bearer {}", token);
    let base = "https://api.ebay.com/sell/account/v1";
    let mkt = urlencoding::encode(&marketplace_id).to_string();

    async fn get_first(
        client: reqwest::Client,
        url: String,
        auth: String,
        array_key: &'static str,
        id_field: &'static str,
        marketplace_id: String,
    ) -> Result<(String, String), String> {
        let resp = client
            .get(&url)
            .header("Authorization", auth)
            .send()
            .await
            .map_err(|e| format!("Request failed: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            if body.contains("20403") || body.contains("not eligible for Business Policy") {
                return Err(
                    "BUSINESS_POLICY_NOT_ENABLED:https://www.bizpolicy.ebay.com/businesspolicy/policyoptin"
                        .to_string(),
                );
            }
            return Err(format!("eBay API error {}: {}", status, body));
        }

        let json: serde_json::Value = resp
            .json()
            .await
            .map_err(|e| format!("Parse error: {}", e))?;

        let arr = json[array_key].as_array().ok_or_else(|| {
            format!(
                "No '{}' array in response. Full response: {}",
                array_key,
                serde_json::to_string(&json).unwrap_or_default()
            )
        })?;

        let policy = arr
            .first()
            .ok_or_else(|| format!("No policies found for marketplace '{}'", marketplace_id))?;

        let id = policy[id_field].as_str().unwrap_or_default().to_string();
        let name = policy["name"].as_str().unwrap_or_default().to_string();
        Ok((id, name))
    }

    let (fulfillment, payment, ret) = tokio::try_join!(
        get_first(
            client.clone(),
            format!("{}/fulfillment_policy?marketplace_id={}", base, mkt),
            auth.clone(),
            "fulfillmentPolicies",
            "fulfillmentPolicyId",
            marketplace_id.clone(),
        ),
        get_first(
            client.clone(),
            format!("{}/payment_policy?marketplace_id={}", base, mkt),
            auth.clone(),
            "paymentPolicies",
            "paymentPolicyId",
            marketplace_id.clone(),
        ),
        get_first(
            client.clone(),
            format!("{}/return_policy?marketplace_id={}", base, mkt),
            auth.clone(),
            "returnPolicies",
            "returnPolicyId",
            marketplace_id.clone(),
        ),
    )?;

    Ok(EbayPolicies {
        fulfillment_policy_id: fulfillment.0,
        fulfillment_policy_name: fulfillment.1,
        payment_policy_id: payment.0,
        payment_policy_name: payment.1,
        return_policy_id: ret.0,
        return_policy_name: ret.1,
    })
}

