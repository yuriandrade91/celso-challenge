// Rotas da API que o proxy do painel aceita encaminhar (allowlist por
// caminho e método). Fica fora do route.ts para poder ser testada: o Next
// não permite exportar outras funções a partir de um ficheiro de rota.
export function isAllowedRequest(path: string[], method: string): boolean {
  if (path.length === 1 && path[0] === "metrics") return method === "GET";
  if (path.length === 1 && path[0] === "upload") return method === "POST";
  if (path[0] === "executions" && path.length <= 2) return method === "GET";
  if (path.length === 1 && path[0] === "reviews") {
    return method === "GET" || method === "POST";
  }
  if (
    path.length === 2 &&
    path[0] === "reviews" &&
    path[1] === "me"
  ) {
    return method === "GET";
  }
  if (
    path.length === 3 &&
    path[0] === "reviews" &&
    /^\d+$/.test(path[1]) &&
    path[2] === "decision"
  ) {
    return method === "PATCH";
  }
  if (
    path.length === 2 &&
    path[0] === "reviews" &&
    /^\d+$/.test(path[1])
  ) {
    return method === "DELETE";
  }
  if (
    path.length === 2 &&
    path[0] === "students" &&
    path[1] === "me"
  ) {
    return method === "GET";
  }
  if (
    path.length === 2 &&
    path[0] === "students" &&
    path[1] === "under-review"
  ) {
    return method === "GET";
  }
  if (path[0] === "terms") {
    if (path.length === 1) return method === "GET" || method === "POST";
    if (!/^\d+$/.test(path[1] ?? "")) return false;
    if (path.length === 2) return method === "PUT" || method === "DELETE";
    if (path.length === 3 && path[2] === "close") return method === "POST";
    if (path.length === 3 && path[2] === "notifications") return method === "GET";
    return false;
  }
  if (path[0] === "notifications") {
    if (path.length === 2 && path[1] === "me") return method === "GET";
    if (path.length === 3 && path[1] === "me" && path[2] === "read-all") {
      return method === "POST";
    }
    if (path.length === 3 && /^\d+$/.test(path[1]) && path[2] === "read") {
      return method === "PATCH";
    }
    return false;
  }
  if (path.length === 1 && path[0] === "students") {
    return method === "GET" || method === "POST";
  }
  if (
    path.length === 2 &&
    path[0] === "students" &&
    path[1] !== "" &&
    path[1] !== "me"
  ) {
    return method === "GET" || method === "PUT" || method === "DELETE";
  }
  return false;
}
