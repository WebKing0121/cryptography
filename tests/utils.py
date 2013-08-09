import os.path


def load_nist_vectors(vector_data, op, fields):
    section, count, data = None, None, {}

    for line in vector_data:
        line = line.strip()

        # Blank lines are ignored
        if not line:
            continue

        # Lines starting with # are comments
        if line.startswith("#"):
            continue

        # Look for section headers
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            data[section] = {}
            continue

        # Build our data using a simple Key = Value format
        name, value = line.split(" = ")

        # COUNT is a special token that indicates a new block of data
        if name.upper() == "COUNT":
            count = value
            data[section][count] = {}
        # For all other tokens we simply want the name, value stored in
        # the dictionary
        else:
            data[section][count][name.lower()] = value

    # We want to test only for a particular operation
    return [
        tuple(vector[1][f].encode("ascii") for f in fields)
        for vector in sorted(data[op].items(), key=lambda v: v[0])
    ]


def load_nist_vectors_from_file(filename, op, fields):
    base = os.path.join(
        os.path.dirname(__file__), "primitives", "vectors", "NIST",
    )
    with open(os.path.join(base, filename), "r") as vector_file:
        return load_nist_vectors(vector_file, op, fields)
