export default function Home() {
  return (
    <>
      <main>
        <div className="eyes" aria-hidden>
          <span className="dot" /><span className="line" /><span className="dot" />
        </div>
        <h1>Hello. I am hiyo, your personal health companion.</h1>
        <div className="card">
          <p style={{ fontSize: 18, lineHeight: 1.6 }}>
            Most AI assistants wait for you to open an app. hiyo watches your
            WHOOP heart rate, knows your calendar, and decides whether a call,
            a gentle text, or simply staying quiet is the right thing —
            and usually chooses <b>not</b> to interrupt you.
          </p>
          <a href="/onboarding" className="pill primary" style={{ textDecoration: "none", marginTop: 8 }}>
            Get started
          </a>
        </div>
      </main>
      <footer>
        Theme inspired by Baymax (Big Hero 6, Disney). Fan tribute, not affiliated. · Not a medical device.
      </footer>
    </>
  );
}
