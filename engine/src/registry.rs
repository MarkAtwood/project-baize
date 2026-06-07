use indexmap::IndexMap;
use serde::{Deserialize, Serialize};

use crate::definition::Visibility;

/// A component registry entry defining a reusable game component set.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RegistryEntry {
    pub id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    pub component_type: ComponentType,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub extends: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subset_of: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shape: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parameterized_by: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub available_colors: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supply: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub count: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub total: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub facing: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flip: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub variants: Option<Variants>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub properties: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sides: Option<IndexMap<String, serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub suits: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub suit_symbols: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub suit_colors: Option<IndexMap<String, String>>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub ranks: Vec<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rank_values: Option<IndexMap<String, serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub extra: Vec<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub composition: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub faces: Option<u32>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub values: Vec<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub display: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub glyphs: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pieces: Option<IndexMap<String, PieceDefinition>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub movement: Option<IndexMap<String, String>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owner_indicated_by: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub special_rules: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub board_constraints: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub distribution: Option<IndexMap<String, TileDistribution>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub denominations: Option<IndexMap<String, serde_json::Value>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub physical_form: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub physical: Option<PhysicalForm>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub visibility: Option<Visibility>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ComponentType {
    Stone,
    Disc,
    Pawn,
    Token,
    Die,
    CardDeck,
    Tile,
    PieceSet,
    Counter,
    Card,
    TileSet,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Variants {
    Named(IndexMap<String, Variant>),
    List(Vec<Variant>),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Variant {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shape: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fill: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stroke: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub glyph: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub glyph_color: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub color: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pattern: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PieceDefinition {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub glyph: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub promoted: Option<PromotedForm>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PromotedForm {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub glyph: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub moves_as: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gains: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TileDistribution {
    pub count: u32,
    pub points: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wildcard: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PhysicalForm {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size_mm: Option<[f64; 2]>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub thickness_mm: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub material: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shape: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub weight_g: Option<f64>,
}

impl RegistryEntry {
    pub fn from_json(json: &str) -> crate::error::Result<Self> {
        serde_json::from_str(json).map_err(Into::into)
    }
}
