use std::collections::{HashMap, HashSet};
use std::path::Path;

use crate::definition::ResourceDef;
use crate::error::{BaizeError, Result};

/// Maximum word list size to prevent unbounded memory allocation.
const MAX_WORD_LIST_ENTRIES: usize = 500_000;
/// Maximum word length to reject garbage input.
const MAX_WORD_LENGTH: usize = 64;
/// Maximum resource file size in bytes.
const MAX_RESOURCE_FILE_BYTES: u64 = 50 * 1024 * 1024; // 50 MB

/// Loaded external resources for a game session.
#[derive(Debug, Clone)]
pub struct ResourceStore {
    word_lists: HashMap<String, HashSet<String>>,
}

impl ResourceStore {
    /// Create an empty resource store (for games with no resources).
    pub fn empty() -> Self {
        Self {
            word_lists: HashMap::new(),
        }
    }

    /// Load all resources declared in the game definition.
    ///
    /// `base_dir` is the directory containing the registry/ subdirectory.
    /// Each resource is resolved to a file path and loaded.
    pub fn load(resources: &indexmap::IndexMap<String, ResourceDef>, base_dir: &Path) -> Result<Self> {
        let mut store = Self::empty();

        for (key, resource) in resources {
            match resource.resource_type.as_str() {
                "word_list" => {
                    let path = base_dir
                        .join("registry")
                        .join("dictionaries")
                        .join(format!("{}.txt", resource.name));
                    let words = Self::load_word_list(&path)?;
                    store.word_lists.insert(key.clone(), words);
                }
                other => {
                    return Err(BaizeError::IllegalAction(format!(
                        "unknown resource type: {other:?} for resource {key:?}"
                    )));
                }
            }
        }

        Ok(store)
    }

    /// Check if a word is valid in the named word list.
    pub fn word_valid(&self, resource_name: &str, word: &str) -> Result<bool> {
        let list = self.word_lists.get(resource_name).ok_or_else(|| {
            BaizeError::IllegalAction(format!(
                "word list resource {resource_name:?} not loaded"
            ))
        })?;
        // Normalize to uppercase for case-insensitive lookup
        Ok(list.contains(&word.to_uppercase()))
    }

    /// Load a word list from a newline-delimited text file.
    fn load_word_list(path: &Path) -> Result<HashSet<String>> {
        // Check file exists
        if !path.exists() {
            return Err(BaizeError::IllegalAction(format!(
                "resource file not found: {}",
                path.display()
            )));
        }

        // Check file size
        let metadata = std::fs::metadata(path).map_err(|e| {
            BaizeError::IllegalAction(format!(
                "cannot read resource file {}: {e}",
                path.display()
            ))
        })?;
        if metadata.len() > MAX_RESOURCE_FILE_BYTES {
            return Err(BaizeError::ResourceBudget(format!(
                "resource file {} is {} bytes, exceeds limit of {} bytes",
                path.display(),
                metadata.len(),
                MAX_RESOURCE_FILE_BYTES
            )));
        }

        // Read and parse
        let content = std::fs::read_to_string(path).map_err(|e| {
            BaizeError::IllegalAction(format!(
                "cannot read resource file {}: {e}",
                path.display()
            ))
        })?;

        let mut words = HashSet::new();
        for line in content.lines() {
            let word = line.trim().to_uppercase();
            if word.is_empty() {
                continue;
            }
            if word.len() > MAX_WORD_LENGTH {
                return Err(BaizeError::IllegalAction(format!(
                    "word too long ({} chars, max {MAX_WORD_LENGTH}): {:?}",
                    word.len(),
                    &word[..32]
                )));
            }
            if words.len() >= MAX_WORD_LIST_ENTRIES {
                return Err(BaizeError::ResourceBudget(format!(
                    "word list exceeds {MAX_WORD_LIST_ENTRIES} entries"
                )));
            }
            words.insert(word);
        }

        Ok(words)
    }
}
