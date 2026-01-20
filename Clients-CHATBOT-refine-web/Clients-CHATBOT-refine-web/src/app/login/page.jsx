'use client';

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { User, Lock, Eye, EyeOff, AlertCircle, Bot } from 'lucide-react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme } from '../../contexts/ThemeContext';
import Image from 'next/image';
import tmsaLogo from '../../../public/assets/tmsa.png';
const TangerMedLogo = ({ isDarkMode }) => (
  <div className="mb-8">
    <div 
      className="w-20 h-20 mx-auto rounded-xl flex items-center justify-center shadow-lg"
      style={{
        background: isDarkMode 
          ? 'linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%)' 
          : 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)'
      }}
    >
      <Bot className="w-10 h-10 text-white" />
    </div>
  </div>
);

export default function LoginPage() {
  const [formData, setFormData] = useState({
    username: '',
    password: ''
  });
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  
  const router = useRouter();
  const { login } = useAuth();
  const { isDarkMode } = useTheme();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const result = await login(formData.username, formData.password);
      
      if (result.success) {
        const redirectPath = new URLSearchParams(window.location.search).get('redirect') || '/dashboard';
        router.push(redirectPath);
      } else {
        setError(result.error || 'Échec de la connexion');
      }
    } catch (error) {
      setError('Une erreur est survenue lors de la connexion');
    } finally {
      setIsLoading(false);
    }
  };

  const handleInputChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };
  // useEffect to log the when the component mounts
  // useEffect(() => {
  //   console.log('LoginPage mounted');
  //   setTimeout(() => {
  //     // seelping
  //   }, 10000);

    // alert('Welcome to the Login Page! Please enter your credentials to continue.');
  // }, []);
  return (
    <div className={`
      min-h-screen flex items-center justify-center p-4
      ${isDarkMode 
        ? 'bg-gradient-to-br from-slate-950 via-slate-900 to-slate-800' 
        : 'bg-gradient-to-br from-slate-50 via-white to-blue-50'
      }
    `}>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="w-full max-w-md"
      >
        <div className={`
          backdrop-blur-lg rounded-2xl p-8 shadow-2xl border
          ${isDarkMode 
            ? 'bg-slate-800/50 border-slate-700/50' 
            : 'bg-white/70 border-slate-200/50'
          }
        `}>
          {/* Logo */}
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.2, duration: 0.5 }}
            className="flex items-center justify-center"
          >
            <Image src={tmsaLogo} alt="TangerMed Logo" width={80} height={80} />

            {/* <TangerMedLogo isDarkMode={isDarkMode} /> */}
          </motion.div>

          {/* Title */}
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.5 }}
            className="text-center mb-8"
          >
            <h1 className={`
              text-3xl font-bold mb-2
              ${isDarkMode ? 'text-slate-100' : 'text-slate-900'}
            `}>
              TangerMed Bot
            </h1>
            <p className={`
              text-sm
              ${isDarkMode ? 'text-slate-300' : 'text-slate-600'}
            `}>
              {/* Connectez-vous à votre assistant intelligent */}
            </p>
            <p className={`
              text-xs mt-2
              ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}
            `}>
              Assistant IA de Tanger Med
            </p>
          </motion.div>

          {/* Error Message */}
          {error && (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              className={`
                mb-6 p-4 rounded-lg flex items-center gap-3
                ${isDarkMode 
                  ? 'bg-red-500/20 border border-red-500/30 text-red-200' 
                  : 'bg-red-50 border border-red-200 text-red-700'
                }
              `}
            >
              <AlertCircle size={20} />
              <span className="text-sm">{error}</span>
            </motion.div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Username Field */}
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.4, duration: 0.5 }}
            >
              <div className="relative">
                <User className={`
                  absolute left-3 top-1/2 transform -translate-y-1/2
                  ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}
                `} size={20} />
                <input
                  type="text"
                  name="username"
                  value={formData.username}
                  onChange={handleInputChange}
                  placeholder="Nom d'utilisateur"
                  required
                  className={`
                    w-full pl-12 pr-4 py-3 rounded-lg transition-all duration-200
                    focus:outline-none focus:ring-2 focus:ring-blue-700 focus:border-transparent
                    ${isDarkMode 
                      ? 'bg-slate-700/50 border border-slate-600/50 text-slate-100 placeholder-slate-400' 
                      : 'bg-white/80 border border-slate-300 text-slate-900 placeholder-slate-500'
                    }
                  `}
                />
              </div>
            </motion.div>

            {/* Password Field */}
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.5, duration: 0.5 }}
            >
              <div className="relative">
                <Lock className={`
                  absolute left-3 top-1/2 transform -translate-y-1/2
                  ${isDarkMode ? 'text-slate-400' : 'text-slate-500'}
                `} size={20} />
                <input
                  type={showPassword ? 'text' : 'password'}
                  name="password"
                  value={formData.password}
                  onChange={handleInputChange}
                  placeholder="Mot de passe"
                  required
                  className={`
                    w-full pl-12 pr-12 py-3 rounded-lg transition-all duration-200
                    focus:outline-none focus:ring-2 focus:ring-blue-700 focus:border-transparent
                    ${isDarkMode 
                      ? 'bg-slate-700/50 border border-slate-600/50 text-slate-100 placeholder-slate-400' 
                      : 'bg-white/80 border border-slate-300 text-slate-900 placeholder-slate-500'
                    }
                  `}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className={`
                    absolute right-3 top-1/2 transform -translate-y-1/2 transition-colors
                    ${isDarkMode 
                      ? 'text-slate-400 hover:text-slate-200' 
                      : 'text-slate-500 hover:text-slate-700'
                    }
                  `}
                >
                  {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                </button>
              </div>
            </motion.div>

            {/* Submit Button */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.6, duration: 0.5 }}
            >
              <button
                type="submit"
                disabled={isLoading}
                className={`
                  w-full py-3 font-semibold rounded-lg transition-all duration-200
                  focus:outline-none focus:ring-2 focus:ring-blue-700 focus:ring-offset-2
                  disabled:opacity-50 disabled:cursor-not-allowed
                  ${isDarkMode 
                    ? 'bg-blue-950 text-white focus:ring-offset-slate-800' 
                    : 'bg-blue-950 text-white focus:ring-offset-slate-800'
                  }
                `}
              >
                {isLoading ? (
                  <div className="flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                    Connexion...
                  </div>
                ) : (
                  'Se connecter'
                )}
              </button>
            </motion.div>

            {/* Sign Up Link */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.7, duration: 0.5 }}
              className="text-center"
            >
              {/* <span className={`
                text-sm
                ${isDarkMode ? 'text-slate-400' : 'text-slate-600'}
              `}>
                Pas encore de compte ?{' '}
                <Link
                  href="/web/signup"
                  className={`
                    transition-colors font-medium
                    ${isDarkMode 
                      ? 'text-blue-700 hover:text-blue-300' 
                      : 'text-blue-700 hover:text-blue-700'
                    }
                  `}
                >
                  S'inscrire
                </Link>
              </span> */}
            </motion.div>
          </form>
        </div>
      </motion.div>
    </div>
  );
}