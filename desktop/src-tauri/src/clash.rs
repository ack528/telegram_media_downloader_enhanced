//! Clash / mihomo external-controller client used by the network page.

use std::time::Duration;

use reqwest::{Client, Method, Url};
use serde::Serialize;
use serde_json::{json, Value as Json};

fn base_url(controller: &str) -> Result<Url, String> {
    let controller = controller.trim().trim_end_matches('/');
    let controller = if controller.is_empty() { "127.0.0.1:9097" } else { controller };
    let with_scheme = if controller.starts_with("http://") || controller.starts_with("https://") {
        controller.to_string()
    } else {
        format!("http://{controller}")
    };
    Url::parse(&with_scheme).map_err(|e| format!("控制器地址无效: {e}"))
}

fn client() -> Client {
    Client::builder().no_proxy().build().expect("http client")
}

async fn call(
    controller: &str,
    secret: &str,
    method: Method,
    segments: &[&str],
    query: &[(&str, String)],
    body: Option<Json>,
    timeout: Duration,
) -> Result<Json, String> {
    let mut url = base_url(controller)?;
    url.path_segments_mut()
        .map_err(|_| "控制器地址无效".to_string())?
        .pop_if_empty()
        .extend(segments);
    if !query.is_empty() {
        url.query_pairs_mut().extend_pairs(query.iter().map(|(k, v)| (*k, v.as_str())));
    }
    let mut request = client().request(method, url).timeout(timeout);
    if !secret.is_empty() {
        request = request.bearer_auth(secret);
    }
    if let Some(body) = body {
        request = request.json(&body);
    }
    let response = request.send().await.map_err(|e| format!("无法连接 Clash 控制器：{e}"))?;
    let status = response.status();
    if status.as_u16() == 401 {
        return Err("Clash 控制器拒绝访问：secret 不正确".into());
    }
    let text = response.text().await.unwrap_or_default();
    if !status.is_success() {
        let message = serde_json::from_str::<Json>(&text)
            .ok()
            .and_then(|v| v.get("message").and_then(|m| m.as_str()).map(str::to_string))
            .unwrap_or_else(|| format!("HTTP {status}"));
        return Err(message);
    }
    Ok(serde_json::from_str(&text).unwrap_or(Json::Null))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClashNode {
    pub name: String,
    pub kind: String,
    pub delay: Option<u64>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClashGroup {
    pub name: String,
    pub kind: String,
    pub now: String,
    pub nodes: Vec<ClashNode>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClashProbe {
    pub version: String,
    pub meta: bool,
    pub mode: String,
    pub groups: Vec<ClashGroup>,
}

fn last_delay(proxy: &Json) -> Option<u64> {
    proxy
        .get("history")
        .and_then(|h| h.as_array())
        .and_then(|h| h.last())
        .and_then(|h| h.get("delay"))
        .and_then(|d| d.as_u64())
        .filter(|d| *d > 0)
}

pub async fn probe(controller: &str, secret: &str) -> Result<ClashProbe, String> {
    let timeout = Duration::from_secs(5);
    let version = call(controller, secret, Method::GET, &["version"], &[], None, timeout).await?;
    let configs = call(controller, secret, Method::GET, &["configs"], &[], None, timeout)
        .await
        .unwrap_or(Json::Null);
    let proxies = call(controller, secret, Method::GET, &["proxies"], &[], None, timeout).await?;
    let proxies = proxies.get("proxies").and_then(|p| p.as_object()).cloned().unwrap_or_default();

    let mut groups: Vec<ClashGroup> = proxies
        .iter()
        .filter(|(name, proxy)| {
            proxy.get("all").and_then(|a| a.as_array()).is_some() && name.as_str() != "GLOBAL"
        })
        .map(|(name, proxy)| {
            let nodes = proxy["all"]
                .as_array()
                .unwrap()
                .iter()
                .filter_map(|n| n.as_str())
                .map(|node| {
                    let info = proxies.get(node);
                    ClashNode {
                        name: node.to_string(),
                        kind: info
                            .and_then(|p| p.get("type"))
                            .and_then(|t| t.as_str())
                            .unwrap_or("")
                            .to_string(),
                        delay: info.and_then(last_delay),
                    }
                })
                .collect();
            ClashGroup {
                name: name.clone(),
                kind: proxy.get("type").and_then(|t| t.as_str()).unwrap_or("").to_string(),
                now: proxy.get("now").and_then(|t| t.as_str()).unwrap_or("").to_string(),
                nodes,
            }
        })
        .collect();
    // Selectors first: those are the groups the downloader can switch.
    groups.sort_by_key(|g| (g.kind != "Selector", g.name.clone()));

    Ok(ClashProbe {
        version: version.get("version").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        meta: version.get("meta").and_then(|v| v.as_bool()).unwrap_or(false),
        mode: configs.get("mode").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        groups,
    })
}

pub async fn delay(controller: &str, secret: &str, name: &str, url: &str, timeout_ms: u64) -> Result<u64, String> {
    let timeout_ms = timeout_ms.clamp(500, 30_000);
    let url = if url.trim().is_empty() { "https://www.gstatic.com/generate_204" } else { url.trim() };
    let result = call(
        controller,
        secret,
        Method::GET,
        &["proxies", name, "delay"],
        &[("timeout", timeout_ms.to_string()), ("url", url.to_string())],
        None,
        Duration::from_millis(timeout_ms + 3000),
    )
    .await?;
    result
        .get("delay")
        .and_then(|d| d.as_u64())
        .ok_or_else(|| "超时".to_string())
}

pub async fn select(controller: &str, secret: &str, group: &str, name: &str) -> Result<(), String> {
    call(
        controller,
        secret,
        Method::PUT,
        &["proxies", group],
        &[],
        Some(json!({ "name": name })),
        Duration::from_secs(5),
    )
    .await
    .map(|_| ())
}
