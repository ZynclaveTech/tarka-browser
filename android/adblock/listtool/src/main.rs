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

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    match args.iter().map(String::as_str).collect::<Vec<_>>().as_slice() {
        [_, "resources", "--ubo", ubo, "--out", out] => resources(Path::new(ubo), Path::new(out)),
        [_, "check", bundle, canaries] => check(Path::new(bundle), Path::new(canaries)),
        _ => {
            eprintln!("usage: listtool resources --ubo DIR --out FILE | listtool check BUNDLE.zip CANARIES.txt");
            ExitCode::from(2)
        }
    }
}
