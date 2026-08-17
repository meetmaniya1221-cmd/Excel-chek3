"""Client configuration and canonical column vocabulary.

Every constant here was recovered from the vendor workbook
(see docs/REVERSE_ENGINEERING.md sections D and F) and is overridable per client.
"""
from dataclasses import dataclass, field


@dataclass
class Config:
    # --- identity ---
    supplier_id: str = ""
    client_name: str = ""

    # --- tax rates (PROVEN exact against 43,490 rows) ---
    tcs_rate: float = 0.005          # 0.5% of taxable value
    tds_rate: float = 0.001          # 0.1% of taxable value
    fee_gst_rate: float = 0.18       # GST charged by Meesho on its fees -> 18/118 extraction

    # --- purchase side ---
    purchase_gst_rate: float = 0.0   # input GST credit on purchases (0 for M Meldi Krupa)
    cost_includes_gst: bool = False

    # Which units consume product cost.
    #
    # An RTO parcel is Returned To Origin -- it comes back to the seller by
    # definition -- and a customer return normally comes back too. So stock is
    # assumed recovered unless a returns export explicitly reports it lost. This
    # matters because returns exports lag: a month whose returns have not been
    # downloaded yet would otherwise have its entire RTO stock written off,
    # inventing a loss out of missing paperwork.
    #   "lost_only"        -> delivered + exchange + units explicitly reported lost
    #                         (default; only what the data proves was never returned)
    #   "delivered"        -> delivered + exchange only; ignores even confirmed losses
    #   "unrecovered"      -> delivered + exchange + every return not confirmed
    #                         recovered. Only meaningful when the returns exports
    #                         cover the whole period, otherwise it overstates cost.
    cost_recognition: str = "lost_only"

    # --- allowances stamped on ads rows in the sample (semantics unconfirmed) ---
    return_loss_allowance: float = 0.0
    rto_packaging_loss_allowance: float = 0.0

    # --- logistics ---
    # Shipping is charged to the customer, and whatever Meesho deducts is already
    # inside Final Settlement Amount, so shipping needs no separate treatment in
    # the P&L. The rate card is therefore optional: supply one only to audit
    # Meesho's shipping deductions against expected rates. Empty = audit off.
    default_weight_slab: str = "Upto 500gm"
    # {(courier, weight_slab): {"forward": x, "return": y}}, negative = a charge
    courier_rate_card: dict = field(default_factory=dict)

    # --- GST ---
    # How the GST line is computed.
    #   "settlement_flat" -> a flat percentage of the settlement actually received
    #                        in the bank. One number, nothing else counted.
    #   "detailed"        -> the full model: output GST on sales, input credit on
    #                        Meesho's fees, input credit on purchases.
    gst_method: str = "settlement_flat"
    gst_settlement_rate: float = 0.05     # 5% of bank settlement
    # Base for that percentage. "net" is the money actually banked, after Meesho
    # nets off returns -- the literal bank settlement. "gross" charges the rate on
    # receipts only and ignores the return reversals.
    gst_settlement_base: str = "net"

    # Only used when gst_method == "detailed":
    # "derive"  -> back-solve fees from the settlement identity, take 18/118 (PROVEN)
    # "columns" -> sum the explicit "GST on ..." columns when the file provides them
    # "auto"    -> use columns when they are populated, else derive
    gst_credit_method: str = "auto"

    # count an order once per sub-order (vendor convention) on its first payment row
    count_orders_on_first_row: bool = True

    # Per-order economics are only meaningful once an order has finished its
    # journey: a shipment still in transit has had its cost incurred but not its
    # settlement received, so including it understates margin per order. When True
    # the KPIs and per-order ratios count only orders in a terminal state.
    final_states_only: bool = True


# Statuses, normalised to the vendor's "Live Order Status 2" vocabulary
STATUS_DELIVERED = "Delivered"
STATUS_RTO = "RTO"
STATUS_RETURN = "Return"
STATUS_EXCHANGE = "Exchange"
STATUS_CANCELLED = "Cancelled"
STATUS_SHIPPED = "Shipped"
STATUS_LOST = "Lost"
STATUS_ADS = "Ads Cost"

# Units that physically reached a customer -> purchase cost is recognised (BR-05)
COST_RECOGNISED_STATUSES = {STATUS_DELIVERED, STATUS_RETURN, STATUS_EXCHANGE}

# An order has finished its journey: the money is settled and the stock position
# is known. Anything else is still moving and distorts per-order averages.
TERMINAL_STATUSES = {STATUS_DELIVERED, STATUS_RETURN, STATUS_RTO,
                     STATUS_EXCHANGE, STATUS_CANCELLED, STATUS_LOST}

# Meesho raw order-status strings -> canonical status
ORDER_STATUS_MAP = {
    "DELIVERED": STATUS_DELIVERED,
    "RTO_COMPLETE": STATUS_RTO,
    "RTO_LOCKED": STATUS_RTO,
    "RTO_INITIATED": STATUS_RTO,
    "RTO_DELIVERY_FAILED": STATUS_RTO,
    "RTO_OFD": STATUS_RTO,
    "RTO": STATUS_RTO,
    "RETURN": STATUS_RETURN,
    "RETURNED": STATUS_RETURN,
    "DOOR_STEP_EXCHANGED": STATUS_EXCHANGE,
    "EXCHANGE": STATUS_EXCHANGE,
    "CANCELLED": STATUS_CANCELLED,
    "CANCEL": STATUS_CANCELLED,
    "SHIPPED": STATUS_SHIPPED,
    "READY_TO_SHIP": STATUS_SHIPPED,
    "PENDING": STATUS_SHIPPED,
    "OUT_FOR_DELIVERY": STATUS_SHIPPED,
    "LOST": STATUS_LOST,
    "SHIPMENT_LOST": STATUS_LOST,
}

# Canonical payment-file fields -> candidate header spellings seen across Meesho
# file generations. Matching is case/punctuation-insensitive (see ingest.normalise_header).
PAYMENT_FIELDS = {
    "sub_order_no":        ["sub order no", "sub order number", "suborder no", "sub_order_no"],
    "order_date":          ["order date"],
    "dispatch_date":       ["dispatch date"],
    "product_name":        ["product name"],
    "supplier_sku":        ["supplier sku", "sku"],
    "live_order_status":   ["live order status", "order status"],
    "product_gst_pct":     ["product gst %", "product gst percent", "product gst"],
    # NB: Meesho ships two file generations. The older one states fees "Excl. GST"
    # with a separate "GST on <fee>" column each; the 2026 one states fees "Incl. GST"
    # and drops those columns. Both spellings are listed so one map reads either.
    "listing_price":       ["listing price incl gst commission", "listing price incl taxes",
                            "listing price"],
    "quantity":            ["quantity", "qty"],
    "transaction_id":      ["transaction id"],
    "payment_date":        ["payment date"],
    "settlement":          ["final settlement amount", "settlement amount"],
    "price_type":          ["price type"],
    "sale_amount":         ["total sale amount incl commission gst",
                            "total sale amount incl shipping gst", "total sale amount"],
    "sale_return_amount":  ["total sale return amount incl shipping gst",
                            "sale return amount incl gst", "total sale return amount",
                            "sale return amount"],
    "fixed_fee_incl":      ["fixed fee incl gst"],
    "warehousing_incl":    ["warehousing fee inc gst", "warehousing fee incl gst"],
    "shipping_revenue":    ["shipping revenue incl gst"],
    "shipping_return_amt": ["shipping return amount incl gst"],
    "return_premium":      ["return premium incl gst"],
    "return_premium_ret":  ["return premium incl gst of return"],
    "commission_pct":      ["meesho commission percentage"],
    "commission":          ["meesho commission excl gst", "meesho commission incl gst"],
    "gold_fee":            ["meesho gold platform fee excl gst",
                            "meesho gold platform fee incl gst"],
    "mall_fee":            ["meesho mall platform fee excl gst",
                            "meesho mall platform fee incl gst"],
    "fixed_fee":           ["fixed fee excl gst"],
    "warehousing_fee":     ["warehousing fee excl gst"],
    "return_ship_charge":  ["return shipping charge excl gst",
                            "return shipping charge incl gst"],
    "gst_compensation":    ["gst compensation prp shipping"],
    "shipping_charge":     ["shipping charge excl gst", "shipping charge incl gst"],
    "other_support":       ["other support service charges excl gst"],
    "waivers":             ["waivers excl gst"],
    "net_other_support":   ["net other support service charges excl gst"],
    "gst_commission":      ["gst on meesho commission"],
    "gst_warehousing":     ["gst on warehousing fee"],
    "gst_gold":            ["gst on meesho gold"],
    "gst_mall":            ["gst on meesho mall platform fee"],
    "gst_shipping":        ["gst on shipping charge", "cgst sgst on shipping charge",
                            "gst on shipping charge cgst sgst on shipping charge"],
    "gst_return_ship":     ["gst on return shipping charge"],
    "gst_net_other":       ["gst on net other support service charges"],
    "gst_fixed_fee":       ["gst on fixed fee"],
    "tcs":                 ["tcs"],
    "tds_rate":            ["tds rate %", "tds rate"],
    "tds":                 ["tds"],
    "compensation":        ["compensation"],
    "claims":              ["claims"],
    "recovery":            ["recovery"],
    "compensation_reason": ["compensation reason"],
    "claims_reason":       ["claims reason"],
    "recovery_reason":     ["recovery reason"],
}

ORDER_FIELDS = {
    "sub_order_no":      ["sub order no", "suborder number", "sub order number", "suborder no"],
    "order_status":      ["reason for credit entry", "order status", "live order status"],
    "catalog_id":        ["catalog id"],
    "order_source":      ["order source"],
    "order_date":        ["order date", "date"],
    "sku":               ["sku", "supplier sku"],
    "size":              ["size"],
    "quantity":          ["quantity", "qty"],
    "customer_state":    ["customer state", "state"],
    "product_name":      ["product name"],
    "listed_price":      ["supplier listed price incl gst commission",
                          "supplier listed price incl gst  commission", "supplier listed price"],
    "discounted_price":  ["supplier discounted price incl gst and commission",
                          "supplier discounted price"],
    "packet_id":         ["packet id"],
}

RETURN_FIELDS = {
    # "Suborder Number" must be listed before any looser spelling: the same export
    # also carries "Order Number" (the parent order), and joining on that would
    # silently merge every sub-order of a multi-item order together.
    "sub_order_no":  ["suborder number", "sub order no", "sub order number", "suborder no"],
    "courier":       ["courier partner", "courier company", "courier", "shipping partner",
                      "logistics partner", "carrier"],
    "return_type":   ["type of return", "return type", "return reason type"],
    "return_subtype": ["sub type", "subtype"],
    "awb":           ["awb number", "awb", "tracking id", "waybill"],
    "return_date":   ["return created date", "return date", "created date"],
    "delivered_date": ["delivered date", "lost date", "expected delivery date"],
    "return_status": ["status"],
    "sku":           ["sku"],
    "qty":           ["qty", "quantity"],
}

CLAIM_FIELDS = {
    "sub_order_no": ["suborder number", "sub order no", "sub order number"],
    "ticket_id":    ["ticket id"],
    "claim_status": ["ticket status", "claim status", "status"],
    "issue":        ["issue"],
    "claim_note":   ["last update"],
    "created_date": ["created date"],
    "sku":          ["sku"],
}

COST_FIELDS = {
    "sku":            ["sku", "supplier sku"],
    # One landed cost per unit is all the sheet asks for. The older split columns
    # are still read so a cost list kept in the previous format still loads.
    "final_cost":     ["final cost", "total cost", "landed cost", "unit cost", "cost"],
    "product_name":   ["product name"],
    "product_cost":   ["product cost", "purchase cost"],
    "packaging_cost": ["pakaging cost", "packaging cost", "packing cost"],
    "gst_pct":        ["purchase gst %", "gst %", "gst percent"],
    "substitute_sku": ["substitute sku", "substitutesku"],
}
