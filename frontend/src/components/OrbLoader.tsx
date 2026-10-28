export default function OrbLoader() {
  return (
    <div className="orb-loader" role="status" aria-label="Loading CodeAtlas">
      <span className="orb-halo" />
      <svg className="orb-graph" viewBox="0 0 88 88" aria-hidden="true">
        <circle className="orb-graph-shell" cx="44" cy="44" r="34" />
        <g className="orb-edges">
          <path d="M44 10 65 17 78 38 70 62 51 77 28 69 10 49 19 26 44 10" />
          <path d="m44 10 1 24 20-17M65 17 53 43l25-5M78 38 53 43l17 19M70 62 53 43l-2 34M51 77 43 57l-15 12M28 69l15-12-23-31M10 49l26-5-17-18M19 26l17 18 9-10" />
          <path d="m36 44 17-1-10 13z" />
        </g>
        <g className="orb-nodes">
          <circle cx="44" cy="10" r="2.5" />
          <circle cx="65" cy="17" r="2.5" />
          <circle cx="78" cy="38" r="2.5" />
          <circle cx="70" cy="62" r="2.5" />
          <circle cx="51" cy="77" r="2.5" />
          <circle cx="28" cy="69" r="2.5" />
          <circle cx="10" cy="49" r="2.5" />
          <circle cx="19" cy="26" r="2.5" />
          <circle cx="36" cy="44" r="2" />
          <circle cx="53" cy="43" r="2.5" />
          <circle cx="43" cy="57" r="2" />
        </g>
      </svg>
      <span className="orb-core" />
    </div>
  );
}
