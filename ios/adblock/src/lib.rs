// Copyright 2026 The Tark Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

//! C interface to adblock-rust for Tark for iOS (see include/tark_adblock.h).
//! Strings cross the boundary as NUL-terminated UTF-8; every string this
//! library returns is freed with tark_string_free.

use adblock::Engine;
use adblock::resources::Resource;
use std::collections::HashSet;
use std::ffi::{CStr, CString, c_char};

pub struct TarkEngine(Engine);

fn to_c(s: String) -> *mut c_char {
    CString::new(s).map(CString::into_raw).unwrap_or(std::ptr::null_mut())
}

/// # Safety
/// `s` is null or a valid NUL-terminated string.
unsafe fn from_c<'a>(s: *const c_char) -> Option<&'a str> {
    if s.is_null() {
        return None;
    }
    unsafe { CStr::from_ptr(s) }.to_str().ok()
}

/// Loads an engine serialized by `listtool engine` and the bundle's
/// resources (redirects and scriptlets, JSON). Null on failure.
///
/// # Safety
/// `dat` points to `dat_len` readable bytes; `resources_json` is a valid
/// NUL-terminated string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tark_engine_new(
    dat: *const u8,
    dat_len: usize,
    resources_json: *const c_char,
) -> *mut TarkEngine {
    if dat.is_null() {
        return std::ptr::null_mut();
    }
    let bytes = unsafe { std::slice::from_raw_parts(dat, dat_len) };
    let mut engine = Engine::default();
    if engine.deserialize(bytes).is_err() {
        return std::ptr::null_mut();
    }
    let Some(resources) = (unsafe { from_c(resources_json) })
        .and_then(|j| serde_json::from_str::<Vec<Resource>>(j).ok())
    else {
        return std::ptr::null_mut();
    };
    engine.use_resources(resources);
    Box::into_raw(Box::new(TarkEngine(engine)))
}

/// # Safety
/// `engine` is null or came from tark_engine_new and is not used again.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tark_engine_free(engine: *mut TarkEngine) {
    if !engine.is_null() {
        drop(unsafe { Box::from_raw(engine) });
    }
}

/// The page's cosmetic resources as JSON: hide_selectors, exceptions,
/// injected_script (scriptlets), generichide, procedural_actions.
///
/// # Safety
/// `engine` came from tark_engine_new; `url` is a valid NUL-terminated string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tark_url_cosmetic_resources(
    engine: *const TarkEngine,
    url: *const c_char,
) -> *mut c_char {
    let (Some(engine), Some(url)) = (unsafe { engine.as_ref() }, unsafe { from_c(url) }) else {
        return std::ptr::null_mut();
    };
    serde_json::to_string(&engine.0.url_cosmetic_resources(url)).map(to_c).unwrap_or(std::ptr::null_mut())
}

/// Generic hide selectors matching the given class and id names (JSON
/// arrays of strings), minus the page's exceptions. Returns a JSON array.
///
/// # Safety
/// `engine` came from tark_engine_new; the others are valid NUL-terminated strings.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tark_hidden_class_id_selectors(
    engine: *const TarkEngine,
    classes_json: *const c_char,
    ids_json: *const c_char,
    exceptions_json: *const c_char,
) -> *mut c_char {
    let Some(engine) = (unsafe { engine.as_ref() }) else {
        return std::ptr::null_mut();
    };
    let parse = |s| -> Vec<String> {
        unsafe { from_c(s) }.and_then(|j| serde_json::from_str(j).ok()).unwrap_or_default()
    };
    let classes = parse(classes_json);
    let ids = parse(ids_json);
    let exceptions: HashSet<String> = parse(exceptions_json).into_iter().collect();
    let selectors = engine.0.hidden_class_id_selectors(&classes, &ids, &exceptions);
    serde_json::to_string(&selectors).map(to_c).unwrap_or(std::ptr::null_mut())
}

/// # Safety
/// `s` is null or a string this library returned, not freed before.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn tark_string_free(s: *mut c_char) {
    if !s.is_null() {
        drop(unsafe { CString::from_raw(s) });
    }
}
