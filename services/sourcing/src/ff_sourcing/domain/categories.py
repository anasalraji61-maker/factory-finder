from __future__ import annotations

from .models import CategoryNode

_T = [
    (
        "product",
        "Products",
        "منتجات",
        [
            ("furniture", "Furniture", "أثاث"),
            ("lighting", "Lighting", "إضاءة"),
            ("solar_energy", "Solar energy", "طاقة شمسية"),
            ("kitchenware", "Kitchenware", "أدوات مطبخ"),
            ("tires_auto", "Tires & auto parts", "إطارات وقطع غيار السيارات"),
            ("apparel", "Apparel & modest wear", "ملابس وأزياء محتشمة"),
            ("tools", "Tools", "عدد وأدوات"),
            ("pumps_hvac", "Pumps & air conditioning", "مضخات وتكييف"),
            ("electronics", "Electronics & security", "إلكترونيات وأنظمة أمان"),
            ("toys_gifts", "Toys & gifts", "ألعاب وهدايا"),
            ("agri_water", "Agriculture & water storage", "زراعة وخزانات مياه"),
            ("health_beauty", "Health & beauty supplies", "مستلزمات صحية وتجميل"),
        ],
    ),
    (
        "raw_material",
        "Raw materials",
        "مواد أولية",
        [
            ("plastics", "Plastics & granules", "بلاستيك وحبيبات"),
            ("metals", "Metals", "معادن"),
            ("textiles", "Textiles & yarn", "منسوجات وخيوط"),
            ("paper_wood", "Paper & wood", "ورق وخشب"),
            ("building_materials", "Building materials", "مواد بناء"),
            ("chemicals", "Fertilizers & chemicals", "أسمدة وكيماويات"),
        ],
    ),
    (
        "production_line",
        "Production lines",
        "خطوط إنتاج",
        [
            ("food_beverage", "Food & beverage lines", "خطوط الأغذية والمشروبات"),
            ("plastics_machinery", "Plastics machinery", "ماكينات البلاستيك"),
            ("metalworking", "Metalworking & CNC", "تشغيل المعادن وCNC"),
            ("construction_machinery", "Construction materials machinery", "ماكينات مواد البناء"),
            ("paper_packaging", "Paper & packaging lines", "خطوط الورق والتغليف"),
            ("textile_garment", "Textile & garment machinery", "ماكينات النسيج والملابس"),
            ("woodworking", "Woodworking machinery", "ماكينات النجارة"),
        ],
    ),
]

CATEGORY_TREE: list[CategoryNode] = [
    CategoryNode(
        slug=s,
        name=n,
        name_ar=a,
        children=[CategoryNode(slug=cs, name=cn, name_ar=ca) for cs, cn, ca in kids],
    )
    for s, n, a, kids in _T
]

_BY_SLUG: dict[str, CategoryNode] = {}
for _top in CATEGORY_TREE:
    _BY_SLUG[_top.slug] = _top
    for _c in _top.children:
        _BY_SLUG[_c.slug] = _c


def expand_category(slug: str) -> set[str]:
    """Leaf slugs covered by a category filter (leaf, or a top-level kind node)."""
    node = _BY_SLUG.get(slug)
    if node is None:
        return {slug}
    return {c.slug for c in node.children} if node.children else {node.slug}


def category_labels(slug: str | None) -> str:
    node = _BY_SLUG.get(slug or "")
    return f"{node.name} {node.name_ar}" if node else ""
