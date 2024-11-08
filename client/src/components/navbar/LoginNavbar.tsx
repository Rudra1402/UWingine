"use client";

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useUserContext } from '@/context/context';
import { handleLogout } from '@/apis/userApis';
import { useRouter } from 'next/navigation';

function Navbar() {
  const router = useRouter();
  const { user, setUser, isLoggedIn, setIsLoggedIn} = useUserContext();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedUser = localStorage.getItem('user');
    if (storedUser) {
      const parsedUser = JSON.parse(storedUser);
      if (parsedUser && parsedUser["user_data"]) {
      setUser(parsedUser["user_data"]);
      setIsLoggedIn(true);
      }
    }
    setLoading(false);
  }, [setUser, setIsLoggedIn]);

  const handleLogoutClick = () => {
    handleLogout(router, setUser, setIsLoggedIn)
  };

  if (loading) {
    return null; // Optionally show a loading spinner
  }

  return (
    <nav className="bg-white shadow-lg">
      <div className="max-w-7xl mx-auto px-6">
        <div className="flex justify-between items-center py-4">
          <Link href="/" className="text-2xl font-bold text-blue-800">
            UWingine
          </Link>
          <div className="hidden md:flex space-x-4">
            {isLoggedIn ? (
              <>
                <Link href="/profile" className="px-4 py-2 text-blue-600">
                  {user?.first_name || 'Profile'}
                </Link>
                <button
                  onClick={handleLogoutClick}
                  className="px-4 py-2 border border-red-600 text-red-600 rounded hover:bg-red-600 hover:text-white transition duration-200"
                >
                  Logout
                </button>
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="px-4 py-2 border border-blue-600 text-blue-600 rounded hover:bg-blue-600 hover:text-white transition duration-200"
                >
                  Login
                </Link>
                <Link
                  href="/signup"
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition duration-200"
                >
                  Sign Up
                </Link>
              </>
            )}
          </div>
          <div className="md:hidden">
            <button
              type="button"
              className="text-gray-600 focus:outline-none focus:text-blue-800"
            >
              <svg
                className="h-6 w-6"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}

export default Navbar;