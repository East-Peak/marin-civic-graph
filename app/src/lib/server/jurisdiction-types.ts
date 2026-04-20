// Single source of truth for which :Place.place_type values count as
// "jurisdictions" in the civic graph. The /about page lists them and the
// homepage status-bar counts them — both predicates must agree or the
// status bar will claim a different number than the list shows.

export const JURISDICTION_PLACE_TYPES = ["city", "town", "county"] as const;

export type JurisdictionPlaceType = (typeof JURISDICTION_PLACE_TYPES)[number];
