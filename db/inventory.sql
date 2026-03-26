-- inventory.sql
-- Closing stock table — updated by DMS daily.
-- closing_stock = 0 means out of stock.
-- Update: UPDATE inventory SET closing_stock=N, last_updated=datetime('now') WHERE product_id='prod_XXX';

CREATE TABLE IF NOT EXISTS inventory (
    product_id      TEXT PRIMARY KEY,
    closing_stock   INTEGER NOT NULL DEFAULT 100,
    last_updated    TEXT NOT NULL,
    updated_by      TEXT DEFAULT 'manual',
    FOREIGN KEY (product_id) REFERENCES products(id)
);

INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_001', 100, datetime('now'), 'seed'); -- New Colour Plus Family Shampoo | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_002', 100, datetime('now'), 'seed'); -- New Colour Plus Family Shampoo | 180 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_003', 100, datetime('now'), 'seed'); -- New Colour Plus Family Shampoo | 450 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_004', 100, datetime('now'), 'seed'); -- Nature Fresh Shampoo (AY) | 180ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_005', 100, datetime('now'), 'seed'); -- Nature Fresh Shampoo (AY) | 500ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_006', 100, datetime('now'), 'seed'); -- Nimson Herbal Shampoo | 500 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_007', 100, datetime('now'), 'seed'); -- Green Apple Shampoo | 500 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_008', 100, datetime('now'), 'seed'); -- Protine Shampoo | 500 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_009', 100, datetime('now'), 'seed'); -- Nimson Amla Hair Oil | 450 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_010', 100, datetime('now'), 'seed'); -- Nimson Amla Hair Oil | 180 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_011', 100, datetime('now'), 'seed'); -- Nimson Amla Hair Oil | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_012', 100, datetime('now'), 'seed'); -- Nimson Coconut Jasmine Hair Oil | 450 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_013', 100, datetime('now'), 'seed'); -- Nimson Coconut Jasmine Hair Oil | 180 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_014', 100, datetime('now'), 'seed'); -- Nimson Coconut Jasmine Hair Oil | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_015', 100, datetime('now'), 'seed'); -- Nimson Keshsilk Plus Hair Oil | 450 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_016', 100, datetime('now'), 'seed'); -- Nimson Keshsilk Plus Hair Oil | 180 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_017', 100, datetime('now'), 'seed'); -- Nimson Keshsilk Plus Hair Oil | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_018', 100, datetime('now'), 'seed'); -- Nimson Keshsilk Plus Hair Oil | 50 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_019', 100, datetime('now'), 'seed'); -- Nimson Kesh Silk Oil | 120 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_020', 100, datetime('now'), 'seed'); -- Nimson Almond Hair Oil | 100ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_021', 100, datetime('now'), 'seed'); -- Nimson Almond Hair Oil | 200 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_022', 100, datetime('now'), 'seed'); -- Nimson Almond Hair Oil | 500 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_023', 100, datetime('now'), 'seed'); -- Divyaratna Cool Cool Hair Oil | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_024', 100, datetime('now'), 'seed'); -- Divyaratna Cool Cool Hair Oil | 180 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_025', 100, datetime('now'), 'seed'); -- Divyaratna Cool Cool Hair Oil | 450 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_026', 100, datetime('now'), 'seed'); -- Coconut Oil | 50 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_027', 100, datetime('now'), 'seed'); -- Coconut Oil | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_028', 100, datetime('now'), 'seed'); -- Coconut Oil | 175 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_029', 100, datetime('now'), 'seed'); -- Coconut Oil | 500 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_030', 100, datetime('now'), 'seed'); -- Nimson Himaryan Hair Oil | 100 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_031', 100, datetime('now'), 'seed'); -- Nimson Himaryan Hair Oil | 200 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_032', 100, datetime('now'), 'seed'); -- Nimson Himaryan Hair Oil | 500 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_033', 100, datetime('now'), 'seed'); -- X-Ice Talcum Powder | 100 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_034', 100, datetime('now'), 'seed'); -- X-Ice Talcum Powder | 20 GM
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_035', 100, datetime('now'), 'seed'); -- Nimson Silk Plus Talcum Powder | 100 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_036', 100, datetime('now'), 'seed'); -- Nimson Silk Plus Talcum Powder | 20 GM
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_037', 100, datetime('now'), 'seed'); -- Nimson Silk Plus Talcum Powder B1G1 | 300 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_038', 100, datetime('now'), 'seed'); -- Nimson Boroneem Talcum Powder B1G1 | 300 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_039', 100, datetime('now'), 'seed'); -- Nimson Boroneem Talcum Powder | 150 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_040', 100, datetime('now'), 'seed'); -- Nimson Boroneem Talcum Powder | 100 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_041', 100, datetime('now'), 'seed'); -- Nimson Boroneem Talcum Powder | 50 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_042', 100, datetime('now'), 'seed'); -- Nimson Boroneem Talcum Powder | 20 GM
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_043', 100, datetime('now'), 'seed'); -- Hair removing Cream (Tube)MIX | 60 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_044', 100, datetime('now'), 'seed'); -- Hair removing Cream (Tube) ROSE | 60 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_045', 100, datetime('now'), 'seed'); -- Hair removing Cream (Tube)MIX | 25 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_046', 100, datetime('now'), 'seed'); -- Hair removing Cream ROSE | 25 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_047', 100, datetime('now'), 'seed'); -- NEW Fruit Glow Bleach | 43 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_048', 100, datetime('now'), 'seed'); -- NEW Fruit Glow Bleach | 9 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_049', 100, datetime('now'), 'seed'); -- NEW Gold Bleach | 43 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_050', 100, datetime('now'), 'seed'); -- NEW Gold Bleach | 9 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_051', 100, datetime('now'), 'seed'); -- Stabary Lip Jelly | 10 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_052', 100, datetime('now'), 'seed'); -- Coffee Lip Jelly | 10 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_053', 100, datetime('now'), 'seed'); -- Nimson Lip Guard | 10 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_054', 100, datetime('now'), 'seed'); -- Nimson Lip Guard | 10 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_055', 100, datetime('now'), 'seed'); -- Happy Lips Strawberry Lip Balm | 5 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_056', 100, datetime('now'), 'seed'); -- Aloevera & Cucumber Hydra Moist.Cream (AY) | 15 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_057', 100, datetime('now'), 'seed'); -- Aloevera & Cucumber Hydra Moist.Cream (AY) | 50 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_058', 100, datetime('now'), 'seed'); -- Aloevera & Cucumber Hydra Moist.Cream (AY) | 100 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_059', 100, datetime('now'), 'seed'); -- Fruit Glow Cream | 15 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_060', 100, datetime('now'), 'seed'); -- Fruit Glow Cream | 50 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_061', 100, datetime('now'), 'seed'); -- Fruit Glow Cream | 100 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_062', 100, datetime('now'), 'seed'); -- Fruit Glow Cream | 200 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_063', 100, datetime('now'), 'seed'); -- Fruit Glow Cream | 400 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_064', 100, datetime('now'), 'seed'); -- Honey & Almond (ayurvedic) | 15 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_065', 100, datetime('now'), 'seed'); -- Honey & Almond (ayurvedic) | 50 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_066', 100, datetime('now'), 'seed'); -- Honey & Almond (ayurvedic) | 100 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_067', 100, datetime('now'), 'seed'); -- Fruitglow Hand & Body Lotion | 20 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_068', 100, datetime('now'), 'seed'); -- Fruitglow Hand & Body Lotion | 90 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_069', 100, datetime('now'), 'seed'); -- Fruitglow Hand & Body Lotion B1G1 | 180 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_070', 100, datetime('now'), 'seed'); -- Fruitglow Hand & Body Lotion B1G1 | 450 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_071', 100, datetime('now'), 'seed'); -- Oats & Olive Moisturising Body Lotion | 20 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_072', 100, datetime('now'), 'seed'); -- Oats & Olive Moisturising Body Lotion | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_073', 100, datetime('now'), 'seed'); -- Oats & Olive Moisturising Body Lotion B1G1 | 180 GM
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_074', 100, datetime('now'), 'seed'); -- Oats & Olive Moisturising Body Lotion B1G1 | 450 GM
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_075', 100, datetime('now'), 'seed'); -- Nimson Ayurvedic Petroleum Jelly | 14 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_076', 100, datetime('now'), 'seed'); -- Nimson Ayurvedic Petroleum Jelly | 21 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_077', 100, datetime('now'), 'seed'); -- Nimson Ayurvedic Petroleum Jelly | 42 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_078', 100, datetime('now'), 'seed'); -- Nimson Ayurvedic Petroleum Jelly | 7 gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_079', 100, datetime('now'), 'seed'); -- Nimson Boroneem Cream | 20 GM
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_080', 100, datetime('now'), 'seed'); -- Olive Body Oil with Italian olives | 100ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_081', 100, datetime('now'), 'seed'); -- Olive Body Oil with Italian olives | 200ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_082', 100, datetime('now'), 'seed'); -- Olive Body Oil with Italian olives | 500ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_083', 100, datetime('now'), 'seed'); -- Glycerin Solutions 3 in 1 Benefirs | 50ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_084', 100, datetime('now'), 'seed'); -- Glycerin Solutions 3 in 1 Benefirs | 110ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_085', 100, datetime('now'), 'seed'); -- Glycerin Solutions 3 in 1 Benefirs | 200ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_086', 100, datetime('now'), 'seed'); -- Gulab Jal Premium Rose water | 50ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_087', 100, datetime('now'), 'seed'); -- Gulab Jal Premium Rose water | 100ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_088', 100, datetime('now'), 'seed'); -- Nature Fresh Brilliantine | 90 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_089', 100, datetime('now'), 'seed'); -- AdI cream 30gm | 25gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_090', 100, datetime('now'), 'seed'); -- Vasojelly Mix | 50 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_091', 100, datetime('now'), 'seed'); -- Vasojelly Mix | 14 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_092', 100, datetime('now'), 'seed'); -- Nimson Vasojelly White Petrolium Jelly | 100ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_093', 100, datetime('now'), 'seed'); -- Nimson Rosemary Hair Oil 150ml + 30ml shampoo | 150ml+30ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_094', 100, datetime('now'), 'seed'); -- Nimson Rosemary Hair Shampoo | 250ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_095', 100, datetime('now'), 'seed'); -- Nimson Rosemary Hair Spray | 110ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_096', 100, datetime('now'), 'seed'); -- Nimson Kerala Ayurvedic Oil | 150ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_097', 100, datetime('now'), 'seed'); -- Nimson Vasojelly Strawberry Crush Face, Hand & Body Cream | 400gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_098', 100, datetime('now'), 'seed'); -- Nimson Vasojelly Soothing Cocoa Face, Hand & Body Cream | 400gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_099', 100, datetime('now'), 'seed'); -- Nimson Vasojelly Fresh Aloe Face, Hand & Body Cream | 400gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_100', 100, datetime('now'), 'seed'); -- Nimson Vasojelly Radiant Glow Face, Hand & Body Cream | 400gm
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_101', 100, datetime('now'), 'seed'); -- Vasojelly Soft Moisturizing Cream | 14 ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_102', 100, datetime('now'), 'seed'); -- Nimson Papaya D-Tan Face Wash | 60ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_103', 100, datetime('now'), 'seed'); -- Nimson Apple Face Wash | 60ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_104', 100, datetime('now'), 'seed'); -- Nimson Strawary Face Wash | 60ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_105', 100, datetime('now'), 'seed'); -- Nimson Neem Tulsi Face Wash | 60ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_106', 100, datetime('now'), 'seed'); -- Charcoal face wash | 60ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_107', 100, datetime('now'), 'seed'); -- Ubtan face wash | 60ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_108', 100, datetime('now'), 'seed'); -- Vitamin C face wash | 60ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_109', 100, datetime('now'), 'seed'); -- Charcoal face wash | 100ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_110', 100, datetime('now'), 'seed'); -- Ubtan face wash | 100ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_111', 100, datetime('now'), 'seed'); -- Vitamin C face wash | 100ML
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_112', 100, datetime('now'), 'seed'); -- Sunscreen SPF 30 PA++ tubes | 60ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_113', 100, datetime('now'), 'seed'); -- Sunscreen SPF 30 PA++ 200 bottle with pump | 200ml
INSERT OR IGNORE INTO inventory (product_id, closing_stock, last_updated, updated_by) VALUES ('prod_114', 100, datetime('now'), 'seed'); -- Nimson Turmeric Cream | 30gm