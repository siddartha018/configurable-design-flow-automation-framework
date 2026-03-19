#include <cerrno>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>

static bool starts_with(const std::string &s, const std::string &prefix) {
  return s.rfind(prefix, 0) == 0;
}

static std::optional<double> parse_runtime_s(const std::string &line) {
  const std::string key = "RUNTIME_S:";
  auto pos = line.find(key);
  if (pos == std::string::npos) return std::nullopt;
  std::string rest = line.substr(pos + key.size());
  // trim leading spaces
  while (!rest.empty() && (rest[0] == ' ' || rest[0] == '\t')) rest.erase(0, 1);
  char *endptr = nullptr;
  errno = 0;
  double val = std::strtod(rest.c_str(), &endptr);
  if (errno != 0 || endptr == rest.c_str()) return std::nullopt;
  return val;
}

int main(int argc, char **argv) {
  if (argc != 2) {
    std::cerr << "usage: log_parser <path_to_log>\n";
    return 2;
  }

  const std::string path = argv[1];
  std::ifstream in(path);
  if (!in.is_open()) {
    std::cerr << "failed to open log file: " << path << "\n";
    return 3;
  }

  int warnings = 0;
  int errors = 0;
  std::optional<double> runtime_s;

  std::string line;
  while (std::getline(in, line)) {
    // Our logs include timestamps, e.g. "<iso> WARN: ...".
    if (line.find(" WARN:") != std::string::npos || starts_with(line, "WARN:")) {
      warnings += 1;
    }
    if (line.find(" ERROR:") != std::string::npos || starts_with(line, "ERROR:")) {
      errors += 1;
    }
    if (auto rt = parse_runtime_s(line); rt.has_value()) {
      runtime_s = rt;
    }
  }

  std::cout << "warnings=" << warnings << "\n";
  std::cout << "errors=" << errors << "\n";
  std::cout << "runtime_s=" << (runtime_s.has_value() ? *runtime_s : 0.0) << "\n";
  return 0;
}

