import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Lab, { activeParameters, displayValue, sliderBounds } from "../Lab";
import { CATALOGUE, PIXEL, PREVIEW, baseRoutes, denoiseAnswer, formEntries, json, mockApi } from "./mockApi";

const png = () => new File(["fake image"], "slice.png", { type: "image/png" });
const sampleBytes = () => new Response(new Uint8Array([137, 80, 78, 71]), { headers: { "Content-Type": "image/png" } });

function routes(extra = {}) {
  const sent = [];
  return {
    sent,
    table: baseRoutes({
      "POST /api/image/preview": PREVIEW,
      "GET /api/samples/cell_phase/file": sampleBytes,
      "POST /api/denoise": request => {
        const fields = formEntries(request.body);
        sent.push(fields);
        return denoiseAnswer(fields.methods.split(","));
      },
      ...extra,
    }),
  };
}

async function ready(user, table, { upload = true } = {}) {
  mockApi(table);
  render(<Lab apiOnline />);
  await screen.findByRole("checkbox", { name: "Mean" });
  if (upload) {
    await user.upload(screen.getByLabelText("Upload an image or DICOM slice"), png());
    await screen.findByAltText(/Preview of slice.png/);
  }
}

const runButton = () => screen.getByRole("button", { name: /run denoising|processing image/i });

describe("2D lab: catalogue and controls", () => {
  it("builds the method list and parameter controls from the API catalogue", async () => {
    const user = userEvent.setup();
    await ready(user, routes().table, { upload: false });
    CATALOGUE.methods.forEach(m => expect(screen.getByRole("checkbox", { name: m.heavy ? `${m.label} slower` : m.label })).toBeInTheDocument());
    CATALOGUE.default_methods.forEach(id => {
      const label = CATALOGUE.methods.find(m => m.id === id).label;
      expect(screen.getByRole("checkbox", { name: label })).toBeChecked();
    });
    expect(screen.getByRole("checkbox", { name: /Non-local means/ })).not.toBeChecked();
    expect(screen.getByLabelText("Kernel size")).toBeInTheDocument();
    expect(screen.queryByLabelText("Filtering strength h")).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Non-local means/ }));
    expect(screen.getByLabelText("Filtering strength h")).toHaveValue("0.15");
    expect(runButton()).toBeDisabled();
    expect(screen.getByText(/Choose an image or a sample to enable the run/)).toBeInTheDocument();
  });

  it("shows the empty state and a retry when the API cannot be reached, then recovers", async () => {
    const user = userEvent.setup();
    const table = routes().table;
    const failing = () => { throw new TypeError("Failed to fetch"); };
    const good = table["GET /api/methods"];
    table["GET /api/methods"] = failing;
    mockApi(table);
    render(<Lab apiOnline={false} />);
    expect(await screen.findByText(/Cannot reach the API/)).toBeInTheDocument();
    expect(screen.getByText("Start with an image")).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
    table["GET /api/methods"] = good;
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByRole("checkbox", { name: "Mean" })).toBeInTheDocument();
    expect(screen.queryByText(/Cannot reach the API/)).not.toBeInTheDocument();
  });

  it("tells the user that files stay on this computer when the API is local", async () => {
    const user = userEvent.setup();
    await ready(user, routes().table, { upload: false });
    expect(screen.getByText(/The API runs on this computer/)).toBeInTheDocument();
  });

  it("requires at least one method", async () => {
    const user = userEvent.setup();
    await ready(user, routes().table);
    for (const id of CATALOGUE.default_methods) {
      await user.click(screen.getByRole("checkbox", { name: CATALOGUE.methods.find(m => m.id === id).label }));
    }
    expect(screen.getByText("Select at least one method.")).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
  });
});

describe("2D lab: input", () => {
  it("previews an uploaded file through the API before anything is processed", async () => {
    const user = userEvent.setup();
    const { table } = routes();
    await ready(user, table);
    expect(screen.getByText("64 × 48 px")).toBeInTheDocument();
    expect(screen.getByText(/Nothing has been computed yet/)).toBeInTheDocument();
    expect(runButton()).toBeEnabled();
  });

  it("loads a bundled sample through the same upload path and shows its provenance and caution", async () => {
    const user = userEvent.setup();
    const { table } = routes();
    const { calls } = mockApi(table);
    render(<Lab apiOnline />);
    await screen.findByRole("checkbox", { name: "Mean" });
    await user.selectOptions(screen.getByLabelText(/bundled sample/i), "cell_phase");
    await screen.findByAltText(/Preview of slice.png/);
    expect(calls.map(c => `${c.method} ${c.url}`)).toEqual(expect.arrayContaining(["GET /api/samples/cell_phase/file", "POST /api/image/preview"]));
    expect(screen.getByText(/not tissue and not a radiological image/)).toBeInTheDocument();
    expect(screen.getByText(/CC0/)).toBeInTheDocument();
    expect(screen.getByText(/Caution:/)).toBeInTheDocument();
    expect(runButton()).toBeEnabled();
  });

  it("drops the previous image when a sample cannot be fetched, so the sample shown is the image that would run", async () => {
    const user = userEvent.setup();
    const table = routes({ "GET /api/samples/cell_phase/file": () => { throw new TypeError("Failed to fetch"); } }).table;
    await ready(user, table);                                              // an uploaded file is loaded first
    expect(runButton()).toBeEnabled();
    await user.selectOptions(screen.getByLabelText(/bundled sample/i), "cell_phase");
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cannot reach the API/);
    expect(runButton()).toBeDisabled();
    expect(screen.queryByAltText(/Preview of/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/bundled sample/i)).toHaveValue("");
  });

  it("never lets the seed exceed what the server accepts", async () => {
    const user = userEvent.setup();
    const { table, sent } = routes();
    await ready(user, table);
    const seed = screen.getByLabelText("Random seed");
    await user.clear(seed);
    await user.type(seed, "99999999999");
    expect(seed).toHaveValue(4294967295);
    await user.click(runButton());
    await screen.findByTestId("lab-results-table");
    expect(sent[0].seed).toBe("4294967295");
  });

  it("rejects an unreadable file with the server's message and keeps the run disabled", async () => {
    const user = userEvent.setup();
    const { table } = routes({ "POST /api/image/preview": () => json({ detail: "Could not read slice.png: Unrecognized image format or corrupted file." }, 400) });
    await ready(user, table, { upload: false });
    await user.upload(screen.getByLabelText("Upload an image or DICOM slice"), png());
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not read slice.png");
    expect(screen.queryByAltText(/Preview of/)).not.toBeInTheDocument();
    expect(runButton()).toBeDisabled();
  });

  it("warns and blocks the run when the image is too large for the slower methods", async () => {
    const user = userEvent.setup();
    const { table } = routes({ "POST /api/image/preview": { ...PREVIEW, width: 2000, height: 2000 } });
    await ready(user, table);
    expect(runButton()).toBeEnabled();
    await user.click(screen.getByRole("checkbox", { name: /Non-local means/ }));
    expect(screen.getByRole("alert")).toHaveTextContent(/limited to 1,048,576 pixels; this image has 4,000,000/);
    expect(runButton()).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /Non-local means/ }));
    expect(runButton()).toBeEnabled();
  });

  it("notes that DICOM scores are on a display scale, not in Hounsfield units", async () => {
    const user = userEvent.setup();
    const { table } = routes({ "POST /api/image/preview": { ...PREVIEW, format: "DICOM" } });
    await ready(user, table);
    expect(screen.getByText(/not in Hounsfield units/)).toBeInTheDocument();
  });
});

describe("2D lab: running an experiment", () => {
  it("sends exactly the chosen settings and shows measured results with parameters and timings", async () => {
    const user = userEvent.setup();
    const { table, sent } = routes();
    await ready(user, table);
    await user.click(screen.getByRole("checkbox", { name: /Non-local means/ }));
    await user.click(runButton());
    const resultsTable = await screen.findByTestId("lab-results-table");
    expect(sent).toHaveLength(1);
    expect(sent[0]).toEqual({
      file: "file:slice.png", noise_type: "Gaussian", noise_amount: "0.02", noise_variance: "0.02", seed: "42",
      methods: "mean,median,gaussian,fft_ideal,fft_gauss,fft_butterworth,nlm",
      kernel_size: "5", sigma: "0", cutoff_ratio: "0.15", nlm_h: "0.15",
    });
    const rows = within(resultsTable).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(8);
    expect(within(rows[0]).getByRole("rowheader")).toHaveTextContent("Noisy input");
    expect(within(rows[7]).getByRole("rowheader")).toHaveTextContent("Non-local means");
    expect(rows[7]).toHaveTextContent("h 0.15, patch size 5, patch distance 6");
    expect(rows[1]).toHaveTextContent("kernel size 5");
    expect(within(rows[1]).getAllByRole("cell").slice(0, 2).map(c => c.textContent)).toEqual(["21", "0.55"]);
    expect(screen.getByText(/LIVE RUN · 25 ms TOTAL/)).toBeInTheDocument();
    expect(screen.getByText(/Gaussian noise, variance 0.02, seed 42. Input: slice.png/)).toBeInTheDocument();
    expect(screen.getByText(/Research and education only/)).toBeInTheDocument();
    expect(screen.getByText("Metrics compare outputs with the original image before synthetic noise was added.")).toBeInTheDocument();
  });

  it("marks the highest PSNR and SSIM of the filtered outputs and does not call any of them 'best'", async () => {
    const user = userEvent.setup();
    await ready(user, routes().table);
    await user.click(runButton());
    const resultsTable = await screen.findByTestId("lab-results-table");
    const topCells = [...resultsTable.querySelectorAll("td.cell-top")];
    expect(topCells).toHaveLength(2);
    expect(within(resultsTable).getAllByRole("row").at(-1)).toContainElement(topCells[0]);
    expect(screen.queryByText(/\bbest\b/i)).not.toBeInTheDocument();
    expect(screen.getByText(/neither shows that anatomy or small structures are preserved/)).toBeInTheDocument();
  });

  it("disables the button and announces progress while the API works, then shows the comparison viewer", async () => {
    const user = userEvent.setup();
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    const { table } = routes({ "POST /api/denoise": async request => { await gate; return denoiseAnswer(formEntries(request.body).methods.split(",")); } });
    await ready(user, table);
    await user.click(runButton());
    const busy = screen.getByRole("button", { name: /processing image/i });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    release();
    await screen.findByTestId("lab-results-table");
    expect(runButton()).toBeEnabled();
    expect(screen.getByTestId("compare")).toBeInTheDocument();
    expect(screen.getByLabelText("Left")).toHaveValue("Noisy input");
    expect(screen.getByLabelText("Right")).toHaveValue("Mean");
    expect(within(screen.getByLabelText("Left")).getByRole("option", { name: "Original input" })).toBeInTheDocument();
  });

  it("moves the comparison divider and switches the compared outputs", async () => {
    const user = userEvent.setup();
    await ready(user, routes().table);
    await user.click(runButton());
    await screen.findByTestId("compare");
    const slider = screen.getByLabelText("Divider position");
    expect(slider).toHaveValue("50");
    const top = screen.getByAltText(/Noisy input, shown on the left/);
    expect(top.style.clipPath).toBe("inset(0 50% 0 0)");
    fireEvent.change(slider, { target: { value: "0" } });
    expect(slider).toHaveValue("0");
    expect(screen.getByAltText(/Noisy input, shown on the left/).style.clipPath).toBe("inset(0 100% 0 0)");
    await user.selectOptions(screen.getByLabelText("Right"), "Median");
    expect(screen.getByAltText(/Median, shown on the right/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Frequency ideal" }));
    expect(screen.getByLabelText("Right")).toHaveValue("Frequency ideal");
  });

  it("shows the server's message when a request is refused and lets the user try again", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const { table } = routes({
      "POST /api/denoise": request => {
        attempts += 1;
        if (attempts === 1) return json({ detail: "Bilateral is limited to 1,048,576 pixels." }, 413);
        return denoiseAnswer(formEntries(request.body).methods.split(","));
      },
    });
    await ready(user, table);
    await user.click(runButton());
    expect(await screen.findByTestId("lab-error")).toHaveTextContent("Bilateral is limited to 1,048,576 pixels.");
    expect(screen.queryByTestId("lab-results-table")).not.toBeInTheDocument();
    expect(runButton()).toBeEnabled();
    await user.click(runButton());
    expect(await screen.findByTestId("lab-results-table")).toBeInTheDocument();
    expect(screen.queryByTestId("lab-error")).not.toBeInTheDocument();
  });

  it("explains a busy server and a lost connection in plain language", async () => {
    const user = userEvent.setup();
    const table = routes({ "POST /api/denoise": () => json({}, 503) }).table;
    await ready(user, table);
    await user.click(runButton());
    expect(await screen.findByTestId("lab-error")).toHaveTextContent(/busy or starting up/);
    table["POST /api/denoise"] = () => { throw new TypeError("Failed to fetch"); };
    await user.click(runButton());
    await waitFor(() => expect(screen.getByTestId("lab-error")).toHaveTextContent(/Cannot reach the API/));
  });

  it("drops stale results when a setting changes and ignores a response that arrives late", async () => {
    const user = userEvent.setup();
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let first = true;
    const { table } = routes({
      "POST /api/denoise": async request => {
        const answer = denoiseAnswer(formEntries(request.body).methods.split(","));
        if (first) { first = false; await gate; }
        return answer;
      },
    });
    await ready(user, table);
    await user.click(runButton());
    await user.click(screen.getByRole("checkbox", { name: "Median" }));       // changes the experiment while the first run is pending
    release();
    await waitFor(() => expect(runButton()).toBeEnabled());
    expect(screen.queryByTestId("lab-results-table")).not.toBeInTheDocument();
    await user.click(runButton());
    const resultsTable = await screen.findByTestId("lab-results-table");
    expect(within(resultsTable).queryByRole("rowheader", { name: "Median" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Mean" }));
    expect(screen.queryByTestId("lab-results-table")).not.toBeInTheDocument();
  });
});

describe("2D lab: helpers", () => {
  const spec = name => CATALOGUE.methods.flatMap(m => m.parameters).find(p => p.name === name);

  it("keeps sliders inside the server's limits", () => {
    expect(sliderBounds(spec("kernel_size"))).toEqual({ min: 1, max: 31 });
    expect(sliderBounds(spec("cutoff_ratio"))).toEqual({ min: 0.01, max: 0.99 });      // the server rejects exactly 1
    expect(sliderBounds(spec("sigma"))).toEqual({ min: 0, max: 50 });
    expect(sliderBounds(spec("bilateral_sigma_color"))).toEqual({ min: 0.01, max: 1 });
  });

  it("formats parameter values for display", () => {
    expect(displayValue(spec("sigma"), 0)).toBe("Auto");
    expect(displayValue(spec("sigma"), 1.5)).toBe("1.5 px");
    expect(displayValue(spec("kernel_size"), 7)).toBe("7 px");
    expect(displayValue(spec("nlm_h"), 0.15)).toBe("0.15 of full range");
  });

  it("lists each shared parameter once, with every method that uses it", () => {
    const params = activeParameters(CATALOGUE.methods, new Set(["mean", "median", "gaussian", "fft_gauss"]));
    expect(params.map(p => p.spec.name)).toEqual(["kernel_size", "sigma", "cutoff_ratio"]);
    expect(params[0].usedBy).toEqual(["Mean", "Median", "Gaussian"]);
    expect(activeParameters(CATALOGUE.methods, new Set())).toEqual([]);
  });

  it("uses real image data URLs in the fixtures", () => {
    expect(PIXEL.startsWith("data:image/png;base64,")).toBe(true);
  });
});
