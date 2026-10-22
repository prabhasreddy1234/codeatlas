export default function OrbLoader() {
  return (
    <div className="orb-loader" role="status" aria-label="Loading CodeAtlas">
      <span className="orb-halo" />
      <span className="orb-ring orb-ring-one" />
      <span className="orb-ring orb-ring-two" />
      <span className="orb-core" />
      <span className="orb-spark" />
    </div>
  );
}
