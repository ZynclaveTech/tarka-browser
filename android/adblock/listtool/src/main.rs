// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! listtool resources --ubo UBO_DIR --out redirects.json
//!   uBlock Origin's redirect resources (src/web_accessible_resources indexed
//!   by src/js/redirect-resources.js), as adblock-rust Resources.
//! listtool check BUNDLE.zip CANARIES.txt
//!   Compiles every list in the bundle with its permission mask, loads the
//!   bundle's resources, round-trips serialize/deserialize and checks each
//!   canary line:
//!     block URL SOURCE TYPE    the request must be blocked
//!     allow URL SOURCE TYPE    the request must not be blocked
//!     script PAGE_URL TEXT     the page's injected scriptlets contain TEXT
//!     hide PAGE_URL SELECTOR   the page's hide selectors contain SELECTOR
//!   Exits 1 on any failure.
//! listtool engine BUNDLE.zip OUT_DIR
//!   Compiles the bundle as `check` does and writes OUT_DIR/engine.dat
//!   (Engine::serialize) and OUT_DIR/resources.json, which Tark for iOS
//!   loads in the app for element hiding and scriptlets.
//! listtool webkit BUNDLE.zip OUT_DIR
//!   Converts the bundle's network rules to WebKit content-blocker rules for
//!   Tark for iOS: OUT_DIR/tark-N.json, each under WebKit's rule limit. Every
//!   file repeats all exception rules after its own block rules, since an
//!   exception only applies within the list it is compiled in. Hide rules are
//!   left out, as Brave does for iOS: WebKit cannot express their per-site
//!   exceptions, and generic ones blank whole sites.

use adblock::lists::{FilterSet, ParseOptions};
use adblock::request::Request;
use adblock::resources::{PermissionMask, Resource};
use adblock::Engine;
use std::io::Read;
use std::path::Path;
use std::process::ExitCode;
use std::time::Instant;

fn resources(ubo: &Path, out: &Path) -> ExitCode {
    let res = adblock::resources::resource_assembler::assemble_web_accessible_resources(
        &ubo.join("src/web_accessible_resources"),
        &ubo.join("src/js/redirect-resources.js"),
    );
    if res.is_empty() {
        eprintln!("no redirect resources found under {}", ubo.display());
        return ExitCode::FAILURE;
    }
    std::fs::write(out, serde_json::to_string(&res).unwrap()).unwrap();
    eprintln!("{} redirect resources", res.len());
    ExitCode::SUCCESS
}

fn read_entry(zip: &mut zip::ZipArchive<std::fs::File>, name: &str) -> String {
    let mut s = String::new();
    zip.by_name(name).unwrap_or_else(|_| panic!("{name} missing")).read_to_string(&mut s).unwrap();
    s
}

fn check(bundle: &Path, canaries: &Path) -> ExitCode {
    let mut zip = zip::ZipArchive::new(std::fs::File::open(bundle).unwrap()).unwrap();
    let manifest: serde_json::Value = serde_json::from_str(&read_entry(&mut zip, "manifest.json")).unwrap();
    let started = Instant::now();
    let mut set = FilterSet::new(false);
    for list in manifest["lists"].as_array().unwrap() {
        let name = list["name"].as_str().unwrap();
        let mask = list["permission"].as_u64().unwrap_or(0) as u8;
        let text = read_entry(&mut zip, &format!("lists/{name}.txt"));
        let opts = ParseOptions { permissions: PermissionMask::from_bits(mask), ..Default::default() };
        set.add_filter_list(text, opts);
    }
    let resources: Vec<Resource> = serde_json::from_str(&read_entry(&mut zip, "resources.json")).unwrap();
    let mut engine = Engine::new_with_filter_set(set);
    engine.use_resources(resources.clone());
    let compiled = started.elapsed();
    let dat = engine.serialize();
    let mut engine = Engine::default();
    if let Err(e) = engine.deserialize(&dat) {
        eprintln!("round-trip failed: {e:?}");
        return ExitCode::FAILURE;
    }
    engine.use_resources(resources);
    eprintln!("compiled in {} ms, engine {} bytes", compiled.as_millis(), dat.len());

    let mut failed = 0;
    for line in std::fs::read_to_string(canaries).unwrap().lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let f: Vec<&str> = line.split_whitespace().collect();
        let ok = match f.as_slice() {
            ["block" | "allow", url, source, kind] => {
                let blocked = Request::new(url, source, kind, "GET")
                    .map(|r| engine.check_network_request(&r).should_block())
                    .unwrap_or(false);
                blocked == (f[0] == "block")
            }
            ["script", page, text] => engine.url_cosmetic_resources(page).injected_script.contains(text),
            ["hide", page, selector] => engine.url_cosmetic_resources(page).hide_selectors.contains(*selector),
            _ => {
                eprintln!("bad canary line: {line}");
                false
            }
        };
        if !ok {
            eprintln!("FAIL {line}");
            failed += 1;
        }
    }
    if failed > 0 { ExitCode::FAILURE } else { ExitCode::SUCCESS }
}

// listtool explain BUNDLE.zip EXTRA_LIST|- ITEM...  (ITEM: req:URL,SOURCE,TYPE
// | page:URL | class:NAME): what the engine decides, for debugging.
fn explain(bundle: &Path, extra: &str, items: &[&str]) -> ExitCode {
    let mut zip = zip::ZipArchive::new(std::fs::File::open(bundle).unwrap()).unwrap();
    let manifest: serde_json::Value = serde_json::from_str(&read_entry(&mut zip, "manifest.json")).unwrap();
    let mut set = FilterSet::new(false);
    for list in manifest["lists"].as_array().unwrap() {
        let name = list["name"].as_str().unwrap();
        let mask = list["permission"].as_u64().unwrap_or(0) as u8;
        let opts = ParseOptions { permissions: PermissionMask::from_bits(mask), ..Default::default() };
        set.add_filter_list(read_entry(&mut zip, &format!("lists/{name}.txt")), opts);
    }
    if extra != "-" {
        let opts = ParseOptions { permissions: PermissionMask::from_bits(1), ..Default::default() };
        set.add_filter_list(std::fs::read_to_string(extra).unwrap(), opts);
    }
    let resources: Vec<Resource> = serde_json::from_str(&read_entry(&mut zip, "resources.json")).unwrap();
    let mut engine = Engine::new_with_filter_set(set);
    engine.use_resources(resources);
    let mut last_exceptions = std::collections::HashSet::new();
    for item in items {
        if let Some(rest) = item.strip_prefix("req:") {
            let f: Vec<&str> = rest.split(',').collect();
            let r = engine.check_network_request(&Request::new(f[0], f[1], f[2], "GET").unwrap());
            println!("{item}: block={} redirect={} exception={}", r.should_block(),
                     r.redirect.as_deref().map(|s| &s[..s.len().min(40)]).unwrap_or("-"), r.exception.is_some());
        } else if let Some(url) = item.strip_prefix("page:") {
            let res = engine.url_cosmetic_resources(url);
            println!("{item}: hide={:?} generichide={} script_len={} script_head={:?}", res.hide_selectors,
                     res.generichide, res.injected_script.len(), &res.injected_script[res.injected_script.len().saturating_sub(400)..]);
            last_exceptions = res.exceptions;
        } else if let Some(class) = item.strip_prefix("class:") {
            println!("{item}: {:?}", engine.hidden_class_id_selectors([class], std::iter::empty::<&str>(), &last_exceptions));
        }
    }
    ExitCode::SUCCESS
}

fn engine(bundle: &Path, out: &Path) -> ExitCode {
    let mut zip = zip::ZipArchive::new(std::fs::File::open(bundle).unwrap()).unwrap();
    let manifest: serde_json::Value = serde_json::from_str(&read_entry(&mut zip, "manifest.json")).unwrap();
    let mut set = FilterSet::new(false);
    for list in manifest["lists"].as_array().unwrap() {
        let name = list["name"].as_str().unwrap();
        let mask = list["permission"].as_u64().unwrap_or(0) as u8;
        let text = read_entry(&mut zip, &format!("lists/{name}.txt"));
        let opts = ParseOptions { permissions: PermissionMask::from_bits(mask), ..Default::default() };
        set.add_filter_list(text, opts);
    }
    let resources = read_entry(&mut zip, "resources.json");
    let dat = Engine::new_with_filter_set(set).serialize();
    std::fs::create_dir_all(out).unwrap();
    std::fs::write(out.join("engine.dat"), &dat).unwrap();
    std::fs::write(out.join("resources.json"), resources).unwrap();
    eprintln!("engine {} bytes", dat.len());
    ExitCode::SUCCESS
}

/// WebKit refuses a content-blocker list with more rules than this.
const WEBKIT_MAX_RULES: usize = 150_000;

fn webkit(bundle: &Path, out: &Path) -> ExitCode {
    use adblock::content_blocking::CbType;
    let mut zip = zip::ZipArchive::new(std::fs::File::open(bundle).unwrap()).unwrap();
    let manifest: serde_json::Value = serde_json::from_str(&read_entry(&mut zip, "manifest.json")).unwrap();
    // Content-blocking conversion needs the raw lines, kept only in debug mode.
    let mut set = FilterSet::new(true);
    let mut lines = 0;
    let network_only = adblock::lists::RuleTypes::NetworkOnly;
    for list in manifest["lists"].as_array().unwrap() {
        let name = list["name"].as_str().unwrap();
        let mask = list["permission"].as_u64().unwrap_or(0) as u8;
        let text = read_entry(&mut zip, &format!("lists/{name}.txt"));
        lines += text.lines().count();
        let opts = ParseOptions {
            permissions: PermissionMask::from_bits(mask),
            rule_types: network_only,
            ..Default::default()
        };
        set.add_filter_list(text, opts);
    }
    let (rules, used) = set.into_content_blocking().expect("debug filter set");
    let (exceptions, blocks): (Vec<_>, Vec<_>) =
        rules.into_iter().partition(|r| matches!(r.action.typ, CbType::IgnorePreviousRules));
    let room = WEBKIT_MAX_RULES - exceptions.len();
    std::fs::create_dir_all(out).unwrap();
    let chunks: Vec<_> = blocks.chunks(room).collect();
    for (i, chunk) in chunks.iter().enumerate() {
        let mut file: Vec<_> = chunk.to_vec();
        file.extend(exceptions.iter().cloned());
        std::fs::write(out.join(format!("tark-{i}.json")), serde_json::to_string(&file).unwrap()).unwrap();
    }
    eprintln!(
        "{lines} lines, {} converted: {} block rules, {} exceptions, {} files",
        used.len(), blocks.len(), exceptions.len(), chunks.len()
    );
    ExitCode::SUCCESS
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    match args.iter().map(String::as_str).collect::<Vec<_>>().as_slice() {
        [_, "resources", "--ubo", ubo, "--out", out] => resources(Path::new(ubo), Path::new(out)),
        [_, "check", bundle, canaries] => check(Path::new(bundle), Path::new(canaries)),
        [_, "explain", bundle, extra, items @ ..] => explain(Path::new(bundle), extra, items),
        [_, "webkit", bundle, out] => webkit(Path::new(bundle), Path::new(out)),
        [_, "engine", bundle, out] => engine(Path::new(bundle), Path::new(out)),
        _ => {
            eprintln!("usage: listtool resources --ubo DIR --out FILE | listtool check BUNDLE.zip CANARIES.txt | listtool webkit|engine BUNDLE.zip OUT_DIR");
            ExitCode::from(2)
        }
    }
}
