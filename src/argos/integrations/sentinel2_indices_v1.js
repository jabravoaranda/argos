//VERSION=3
function setup() {
  return {
    input: ["B04", "B05", "B08", "B8A", "B11", "SCL", "dataMask"],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32" },
      { id: "savi", bands: 1, sampleType: "FLOAT32" },
      { id: "ndre", bands: 1, sampleType: "FLOAT32" },
      { id: "ndmi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 }
    ]
  };
}

function isValidSample(sample) {
  return sample.dataMask === 1 && (sample.SCL === 4 || sample.SCL === 5);
}

function safeIndex(numerator, denominator) {
  if (denominator === 0 || !isFinite(numerator) || !isFinite(denominator)) {
    return NaN;
  }
  return numerator / denominator;
}

function evaluatePixel(sample) {
  const valid = isValidSample(sample);
  const ndvi = safeIndex(sample.B08 - sample.B04, sample.B08 + sample.B04);
  const savi = 1.5 * safeIndex(sample.B08 - sample.B04, sample.B08 + sample.B04 + 0.5);
  const ndre = safeIndex(sample.B8A - sample.B05, sample.B8A + sample.B05);
  const ndmi = safeIndex(sample.B08 - sample.B11, sample.B08 + sample.B11);
  const mask = valid && isFinite(ndvi) && isFinite(savi) && isFinite(ndre) && isFinite(ndmi) ? 1 : 0;
  return {
    ndvi: [mask ? ndvi : NaN],
    savi: [mask ? savi : NaN],
    ndre: [mask ? ndre : NaN],
    ndmi: [mask ? ndmi : NaN],
    dataMask: [mask]
  };
}
