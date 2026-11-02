-- Product IDs come from the source JSON rather than a generated sequence.
CREATE TABLE IF NOT EXISTS public.products (
    id BIGINT PRIMARY KEY,
    name TEXT NOT NULL,
    url_key TEXT NOT NULL,
    price NUMERIC(18, 0) NOT NULL CHECK (price >= 0),
    description TEXT,
    images_url TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
);
