import { PythonBridge } from "./python-bridge";
const py = new PythonBridge();
const getAuth = async () => {
  await py.init();
  const result = await py.call("exegia.auth");
  return result;
};

const end = async () => {
  await py.shutdown();
};

export { getAuth, end }
