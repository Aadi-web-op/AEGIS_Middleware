/**
 * Example inputs for Live evaluation. They only prefill the form; the
 * decision always comes from POST /v1/evaluate. Wording is taken from the
 * benchmark cases in tests/benchmark/test_cases.py.
 */

const today = () => new Date().toISOString().slice(0, 10);

export const EXAMPLES = [
  {
    id: "supported",
    label: "Supported",
    build: () => ({
      query: "How many casual leaves can an employee take annually?",
      answer: "Full-time employees are entitled to 18 casual leaves per year.",
      profile: "standard",
      time_sensitive: true,
      evidence: [
        {
          text: "Full-time employees are entitled to 18 casual leaves per calendar year.",
          source: "leave_policy_2026.pdf",
          version: "v3",
          date: today(),
        },
      ],
    }),
  },
  {
    id: "unsupported",
    label: "Unsupported claim",
    build: () => ({
      query: "How many weeks of paid maternity leave can faculty members claim?",
      answer: "Faculty members are entitled to 26 weeks of paid maternity leave.",
      profile: "standard",
      time_sensitive: true,
      evidence: [
        {
          text: "Staff leave rules encompass casual leave (18 days) and earned leave (30 days).",
          source: "leave_policy_summary.pdf",
          version: "v1",
          date: today(),
        },
      ],
    }),
  },
  {
    id: "contradictory",
    label: "Contradictory sources",
    build: () => ({
      query: "How many annual sick leave days are sanctioned for university personnel?",
      answer: "University personnel are entitled to 14 days of sick leave annually.",
      profile: "standard",
      time_sensitive: true,
      evidence: [
        {
          text: "University employees are granted 10 days of medical leave per calendar year upon doctor certification.",
          source: "hr_circular_2024.pdf",
          version: "v1",
          date: today(),
        },
        {
          text: "Medical and sick leave entitlement for university personnel is established at 14 days per calendar year.",
          source: "hr_circular_2026.pdf",
          version: "v2",
          date: today(),
        },
      ],
    }),
  },
  {
    id: "outdated",
    label: "Outdated version",
    build: () => ({
      query: "How many emergency sick leaves can be granted without prior medical certificate?",
      answer: "Employees may take up to 3 days of emergency sick leave without a prior medical certificate.",
      profile: "standard",
      time_sensitive: true,
      evidence: [
        {
          text: "Up to 3 emergency sick days may be taken without a prior doctor certificate under emergency provisions.",
          source: "leave_circular_2022.pdf",
          version: "v1",
          date: "2022-01-01",
        },
        {
          text: "All sick leaves of any duration strictly require a medical certificate submitted within 24 hours.",
          source: "leave_circular_2026.pdf",
          version: "v3",
          date: today(),
        },
      ],
    }),
  },
];

export const EMPTY_EVIDENCE = { text: "", source: "", version: "", date: "" };
