export type MesSource = {
    system: string;
    origin: string;
    fact_role: string;
    environment: string;
    site_code: string;
    namespace: string;
};
export type MesScope = Record<string, string | number>;
export type MesKind = 'orders' | 'order-materials' | 'priority' | 'iqc';
export type MesStatus = {
    configured: boolean;
    can_refresh: boolean;
    source: MesSource | null;
    refresh_error?: {
        code: string;
        message: string;
    };
};
export type MesOrder = {
    shop_order: string;
    description: string | null;
    created_at?: string | null;
    has_components?: boolean;
};
export type MesData = {
    items?: MesOrder[];
    next_cursor?: string | null;
    total?: number | null;
    total_items?: number;
    components?: {
        component_key: string;
        material_id: string;
        unit?: string;
        required_quantity?: string;
        withdrawn_quantity?: string | null;
    }[];
    rows?: Record<string, unknown>[];
};
export type MesObservation = {
    snapshot: null | {
        id: string;
        kind: string;
        scope: MesScope;
        source: MesSource;
        collected_at: string;
        data: MesData;
    };
    refresh_error: null | {
        code: string;
        message: string;
    };
};
// A source order is meaningful only within the source and account that supplied it.
export type MesOrderSelection = Readonly<{
    accountId: string;
    source: Readonly<MesSource>;
    order: Readonly<MesOrder>;
}>;
