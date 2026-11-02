INSERT INTO public.products (id, name, url_key, price, description, images_url)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    url_key = EXCLUDED.url_key,
    price = EXCLUDED.price,
    description = EXCLUDED.description,
    images_url = EXCLUDED.images_url;
